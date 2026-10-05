"""Pure statistics and aligned comparisons for the local GUI."""

from __future__ import annotations

import math

import pytest

from bancada.gui.metrics import case_passed, compare_runs, run_metrics
from bancada.models import CaseResult, CheckOutcome, Difficulty, Gabarito, Run, Stance


def _result(
    case_id: str,
    *,
    passed: bool = True,
    category: str = "codigo",
    suite: str = "code",
    score: float | None = None,
    auto: bool = False,
    tps: float | None = None,
    total_ms: float = 10,
    prompt_ms: float | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    error: str | None = None,
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        suite=suite,
        category=category,
        source="manual",
        prompt="prompt",
        reply="reply",
        checks=[CheckOutcome(type="machine", ok=passed)],
        total_ms=total_ms,
        ttft_ms=prompt_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tokens_per_second=tps,
        fail_class="error" if error else "ok" if passed else "model",
        fail_reason=error or ("" if passed else "wrong answer"),
        difficulty=Difficulty.FACIL,
        error=error,
        gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
    )


def _run(run_id: str, *results: CaseResult, **config: object) -> Run:
    model_id = str(config.pop("model_id", "model-a"))
    config.setdefault("suite_versions", {"code": 3, "imported/code": 2})
    return Run(
        id=run_id,
        model_id=model_id,
        endpoint="http://127.0.0.1:8080/v1",
        results=list(results),
        **config,
    )


def test_missing_metrics_and_partial_judge() -> None:
    run = _run(
        "partial",
        _result("scored", score=3, auto=True, tps=30),
        _result("unscored", score=None, tps=None),
    )
    run.judge_scores = {
        "cases": [
            {"id": "scored", "score": 3, "auto": True},
            {"id": "invalid", "score": 5},
            {"id": "nan", "score": math.nan},
        ]
    }

    summary = run_metrics(run)

    assert summary["judge_mean"] == 3
    assert summary["judge_count"] == 1
    assert summary["judge_by_case"] == {
        "scored": {"score": 3, "auto": True}
    }
    assert summary["tps_p50"] == 30
    assert summary["tps_count"] == 1

    empty = run_metrics(_run("empty"))
    assert empty["judge_mean"] is None
    assert empty["tps_p50"] is None
    assert empty["machine_rate"] is None


def test_judge_zero_score_is_valid_and_keeps_auto_flag() -> None:
    run = _run("zero", _result("case"))
    run.judge_scores = {"cases": [{"id": "case", "score": 0, "auto": True}]}

    summary = run_metrics(run)

    assert summary["judge_mean"] == 0
    assert summary["judge_count"] == 1
    assert summary["judge_by_case"]["case"] == {"score": 0, "auto": True}


def test_judge_duplicate_ids_count_once_and_last_valid_score_wins() -> None:
    run = _run("duplicates", _result("x"))
    run.judge_scores = {
        "cases": [
            {"id": "x", "score": 0, "auto": True},
            {"id": "x", "score": 3, "auto": False},
            {"id": "outside", "score": 2, "auto": True},
        ]
    }

    summary = run_metrics(run)

    assert summary["judge_count"] == 1
    assert summary["judge_mean"] == 3
    assert summary["judge_by_case"] == {"x": {"score": 3, "auto": False}}


def test_orphan_judgements_do_not_count_toward_coverage() -> None:
    run = _run("orphan", _result("recorded"))
    run.judge_scores = {"cases": [{"id": "outside", "score": 3}]}

    summary = run_metrics(run)
    empty_summary = run_metrics(
        _run("empty").model_copy(update={"judge_scores": run.judge_scores})
    )

    assert summary["judge_mean"] is None
    assert summary["judge_count"] == 0
    assert summary["judge_by_case"] == {}
    assert empty_summary["judge_mean"] is None
    assert empty_summary["judge_count"] == 0


def test_negative_token_counts_do_not_count_as_measurements() -> None:
    run = _run(
        "tokens",
        _result("negative", prompt_tokens=-4, completion_tokens=-2),
        _result("zero", prompt_tokens=0, completion_tokens=0),
        _result("missing"),
    )

    summary = run_metrics(run)

    assert summary["prompt_tokens_sum"] == 0
    assert summary["prompt_tokens_count"] == 1
    assert summary["completion_tokens_sum"] == 0
    assert summary["completion_tokens_count"] == 1


def test_default_latency_without_payload_field_is_not_measured() -> None:
    legacy = CaseResult.model_validate(_result("legacy").model_dump(exclude={"total_ms"}))
    summary = run_metrics(_run("legacy", legacy))

    assert "total_ms" not in legacy.model_fields_set
    assert summary["latency_p50_ms"] is None
    assert summary["latency_p95_ms"] is None
    assert summary["latency_count"] == 0
    assert summary["time_sum_ms"] == 0

    explicit_zero = run_metrics(_run("zero-latency", _result("zero", total_ms=0)))
    assert explicit_zero["latency_p50_ms"] == 0
    assert explicit_zero["latency_count"] == 1


def test_comparison_warns_when_harness_is_only_a_default() -> None:
    a = _run("a", _result("x"))
    b = _run("b", _result("x"))

    harness_warning = next(
        warning
        for warning in compare_runs(a, b)["warnings"]
        if warning["field"] == "harness"
    )

    assert "harness" not in a.model_fields_set
    assert harness_warning["a"] == harness_warning["b"] == "direct"
    assert harness_warning["missing"] == ["a", "b"]


def test_case_passed_requires_checks_and_no_error() -> None:
    assert case_passed(_result("yes"))
    assert not case_passed(_result("none").model_copy(update={"checks": []}))
    assert not case_passed(_result("error", error="timeout"))
    assert not case_passed(_result("failed", passed=False))


def test_run_metrics_preserve_enem_groups_and_sparse_measurements() -> None:
    run = _run(
        "summary",
        _result("a", passed=True, total_ms=10, prompt_ms=4, prompt_tokens=3),
        _result("b", passed=False, total_ms=20, prompt_ms=math.inf, completion_tokens=5),
        _result(
            "c",
            passed=True,
            total_ms=math.inf,
            error="timeout",
            tps=12,
            prompt_ms=8,
            prompt_tokens=7,
            completion_tokens=9,
        ),
    )

    summary = run_metrics(run)

    assert summary["total"] == 3
    assert summary["passed"] == 1
    assert summary["machine_rate"] == pytest.approx(1 / 3)
    assert summary["enem"]["enem_score"] == round(1 / 3, 4)
    assert summary["categories"]["codigo"] == {
        "passed": 1,
        "total": 3,
        "rate": pytest.approx(1 / 3),
    }
    assert summary["difficulties"]["facil"] == {
        "passed": 1,
        "total": 3,
        "rate": pytest.approx(1 / 3),
    }
    assert summary["fail_reasons"] == {"wrong answer": 1, "timeout": 1}
    assert summary["latency_p50_ms"] == 15
    assert summary["latency_p95_ms"] == 19.5
    assert summary["time_sum_ms"] == 30
    assert summary["tps_p50"] == 12
    assert summary["tps_count"] == 1
    assert summary["prompt_tokens_sum"] == 10
    assert summary["prompt_tokens_count"] == 2
    assert summary["completion_tokens_sum"] == 14
    assert summary["completion_tokens_count"] == 2
    assert summary["prompt_processing_sum_ms"] == 12
    assert summary["prompt_processing_count"] == 2


def test_comparison_only_scores_common_cases() -> None:
    a = _run("a", _result("x", passed=False), _result("y", passed=True))
    b = _run("b", _result("x", passed=True), _result("z", passed=False))

    comparison = compare_runs(a, b)

    assert comparison["common_total"] == 1
    assert comparison["only_a"] == ["y"]
    assert comparison["only_b"] == ["z"]
    assert comparison["common_pass_a"] == 0
    assert comparison["common_pass_b"] == 1
    assert comparison["rows"] == [
        {"case_id": "x", "pass_a": False, "pass_b": True, "status": "improvement"}
    ]


def test_comparison_warns_on_config_difference_and_ambiguous_history() -> None:
    a = _run(
        "a",
        _result("x", suite="humaneval", category="codigo"),
        model_id="model-a",
        seed=42,
        suite_versions={"code": 3},
        temperature=0,
        max_tokens=512,
        timeout=30,
        harness="direct",
    )
    b = _run(
        "b",
        _result("x", suite="humaneval", category="codigo"),
        model_id="model-b",
        seed=43,
        suite_versions={"imported/code": 2},
        temperature=0.2,
        max_tokens=256,
        timeout=60,
        harness="pi",
    )

    warnings = compare_runs(a, b)["warnings"]

    assert {warning["field"] for warning in warnings} >= {
        "seed",
        "suite_versions",
        "temperature",
        "max_tokens",
        "timeout",
        "harness",
    }
    assert "model_id" not in {warning["field"] for warning in warnings}
    assert any(
        warning["field"] == "suite_versions" and warning["ambiguous"]
        for warning in warnings
    )

    missing = compare_runs(
        _run("old", _result("x"), suite_versions={}),
        _run("new", _result("x"), suite_versions={}),
    )["warnings"]
    assert "suite_versions" in {warning["field"] for warning in missing}


def test_comparison_rejects_duplicate_case_ids() -> None:
    run = _run("dup", _result("x"), _result("x", passed=False))

    with pytest.raises(ValueError, match="duplicate case IDs"):
        compare_runs(run, _run("other", _result("x")))
