"""Pure run statistics and case-aligned comparisons for the local GUI."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from bancada.aggregate import _category, _difficulty, _passed, summarize_run
from bancada.models import CaseResult, Run


def case_passed(result: CaseResult) -> bool:
    """Return whether every existing machine check passed without a run error."""
    return _passed(result)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _judge_data(run: Run) -> tuple[float | None, int, dict[str, dict[str, Any]]]:
    payload = run.judge_scores or {}
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        return None, 0, {}

    scores: list[float] = []
    by_case: dict[str, dict[str, Any]] = {}
    for item in cases:
        if not isinstance(item, Mapping):
            continue
        case_id = item.get("id")
        score = _finite_number(item.get("score"))
        if not isinstance(case_id, str) or score is None or not 0 <= score <= 3:
            continue
        scores.append(score)
        entry: dict[str, Any] = {"score": score}
        if isinstance(item.get("auto"), bool):
            entry["auto"] = item["auto"]
        by_case[case_id] = entry
    return (sum(scores) / len(scores) if scores else None, len(scores), by_case)


def run_metrics(run: Run) -> dict[str, Any]:
    """Summarize a run, retaining explicit sample counts for sparse measurements."""
    results = run.results
    passed = [case_passed(result) for result in results]
    category_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    difficulty_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    latencies: list[float] = []
    speeds: list[float] = []
    prompt_times: list[float] = []
    prompt_tokens: list[int] = []
    completion_tokens: list[int] = []
    time_sum = 0.0

    for result, ok in zip(results, passed, strict=True):
        category_counts[_category(result)][1] += 1
        category_counts[_category(result)][0] += int(ok)
        difficulty = _difficulty(result).value
        difficulty_counts[difficulty][1] += 1
        difficulty_counts[difficulty][0] += int(ok)

        speed = _finite_number(result.tokens_per_second)
        if speed is not None and speed >= 0:
            speeds.append(speed)
        prompt_time = _finite_number(result.ttft_ms)
        if prompt_time is not None and prompt_time >= 0:
            prompt_times.append(prompt_time)
        if isinstance(result.prompt_tokens, int) and not isinstance(result.prompt_tokens, bool):
            prompt_tokens.append(result.prompt_tokens)
        if isinstance(result.completion_tokens, int) and not isinstance(
            result.completion_tokens, bool
        ):
            completion_tokens.append(result.completion_tokens)
        if result.error:
            continue
        latency = _finite_number(result.total_ms)
        if latency is not None and latency >= 0:
            latencies.append(latency)
            time_sum += latency

    judge_mean, judge_count, judge_by_case = _judge_data(run)
    total = len(results)
    enem = summarize_run(run)

    def groups(counts: dict[str, list[int]]) -> dict[str, dict[str, int | float | None]]:
        return {
            name: {
                "passed": values[0],
                "total": values[1],
                "rate": values[0] / values[1] if values[1] else None,
            }
            for name, values in sorted(counts.items())
        }

    return {
        "total": total,
        "passed": sum(passed),
        "machine_rate": sum(passed) / total if total else None,
        "enem": enem,
        "categories": groups(category_counts),
        "difficulties": groups(difficulty_counts),
        "fail_reasons": enem["fail_reasons"],
        "judge_mean": judge_mean,
        "judge_count": judge_count,
        "judge_by_case": judge_by_case,
        "tps_p50": _percentile(speeds, 0.5),
        "tps_count": len(speeds),
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "time_sum_ms": time_sum,
        "latency_count": len(latencies),
        "prompt_tokens_sum": sum(prompt_tokens),
        "prompt_tokens_count": len(prompt_tokens),
        "completion_tokens_sum": sum(completion_tokens),
        "completion_tokens_count": len(completion_tokens),
        "prompt_processing_p50_ms": _percentile(prompt_times, 0.5),
        "prompt_processing_sum_ms": sum(prompt_times),
        "prompt_processing_count": len(prompt_times),
    }


_COMPARISON_FIELDS = (
    "seed",
    "suite_versions",
    "temperature",
    "max_tokens",
    "timeout",
    "harness",
)


def _has_imported_cases(run: Run) -> bool:
    return any(result.source == "imported" or result.suite == "humaneval" for result in run.results)


def _ambiguous_imported_versions(run: Run) -> bool:
    versions = run.suite_versions
    return _has_imported_cases(run) and "imported/code" not in versions and "code" in versions


def _config_warnings(a: Run, b: Run) -> list[dict[str, Any]]:
    warnings = []
    for field in _COMPARISON_FIELDS:
        value_a = getattr(a, field)
        value_b = getattr(b, field)
        missing_a = value_a is None or (field == "suite_versions" and not value_a)
        missing_b = value_b is None or (field == "suite_versions" and not value_b)
        ambiguous = field == "suite_versions" and (
            _ambiguous_imported_versions(a) or _ambiguous_imported_versions(b)
        )
        if missing_a or missing_b or value_a != value_b or ambiguous:
            warnings.append(
                {
                    "field": field,
                    "a": value_a,
                    "b": value_b,
                    "missing": [
                        name
                        for name, value in (("a", value_a), ("b", value_b))
                        if value is None or (field == "suite_versions" and not value)
                    ],
                    "ambiguous": ambiguous,
                }
            )
    return warnings


def _index_results(run: Run) -> dict[str, CaseResult]:
    indexed: dict[str, CaseResult] = {}
    duplicates: set[str] = set()
    for result in run.results:
        if result.case_id in indexed:
            duplicates.add(result.case_id)
        indexed[result.case_id] = result
    if duplicates:
        repeated = ", ".join(sorted(duplicates))
        raise ValueError(f"duplicate case IDs: {repeated}")
    return indexed


def compare_runs(a: Run, b: Run) -> dict[str, Any]:
    """Compare common cases by ID and report configuration differences separately."""
    indexed_a = _index_results(a)
    indexed_b = _index_results(b)
    common = indexed_a.keys() & indexed_b.keys()
    rows = []
    for case_id in indexed_a:
        if case_id not in common:
            continue
        pass_a = case_passed(indexed_a[case_id])
        pass_b = case_passed(indexed_b[case_id])
        status = (
            "maintained"
            if pass_a and pass_b
            else "regression"
            if pass_a
            else "improvement"
            if pass_b
            else "failed"
        )
        rows.append(
            {"case_id": case_id, "pass_a": pass_a, "pass_b": pass_b, "status": status}
        )
    only_a = [case_id for case_id in indexed_a if case_id not in indexed_b]
    only_b = [case_id for case_id in indexed_b if case_id not in indexed_a]
    common_pass_a = sum(row["pass_a"] for row in rows)
    common_pass_b = sum(row["pass_b"] for row in rows)
    return {
        "rows": rows,
        "common_total": len(rows),
        "common_pass_a": common_pass_a,
        "common_pass_b": common_pass_b,
        "common_rate_a": common_pass_a / len(rows) if rows else None,
        "common_rate_b": common_pass_b / len(rows) if rows else None,
        "only_a": only_a,
        "only_b": only_b,
        "warnings": _config_warnings(a, b),
    }
