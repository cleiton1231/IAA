"""Render a Markdown judge packet from a stored run."""

from __future__ import annotations

import json
import statistics

from bancada.models import CaseResult, Run


def render_packet(run: Run) -> str:
    latencies = [item.total_ms for item in run.results if item.error is None]
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    lines = [
        "# Bancada judge packet",
        "",
        f"- run_id: `{run.id}`",
        f"- model: `{run.model_id}`",
        f"- endpoint: `{run.endpoint}`",
        f"- suite_versions: `{json.dumps(run.suite_versions)}`",
        f"- cases: {len(run.results)}",
        f"- latency_p50_ms: {p50}",
        f"- latency_p95_ms: {p95}",
        "",
        "Leia `JUDGE.md`. Pontue cada caso. Não se impressione com fluência.",
        "",
    ]
    for result in run.results:
        lines.extend(_case_block(result))
    template = {
        "run_id": run.id,
        "judge": "grok-chat",
        "cases": [
            {"id": item.case_id, "score": None, "max": 3, "reason": ""}
            for item in run.results
        ],
    }
    lines.extend(
        [
            "## Template JSON para o juiz",
            "",
            "```json",
            json.dumps(template, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _case_block(result: CaseResult) -> list[str]:
    checks = ", ".join(
        f"{c.type}={'pass' if c.ok else 'fail'}" + (f" ({c.reason})" if c.reason else "")
        for c in result.checks
    ) or "(none)"
    gab = result.gabarito
    return [
        f"## {result.case_id}",
        "",
        f"- source: {result.source}",
        f"- suite: {result.suite}",
        f"- total_ms: {result.total_ms:.1f}",
        f"- error: {result.error or 'none'}",
        f"- machine_checks: {checks}",
        f"- stance: `{gab.stance.value}`",
        f"- must_cover: {gab.must_cover}",
        f"- must_not: {gab.must_not}",
        f"- gabarito_notes: {gab.notes or '(none)'}",
        "",
        "### Prompt",
        "",
        "```",
        result.prompt.rstrip(),
        "```",
        "",
        "### Reply",
        "",
        "```",
        (result.reply or "").rstrip() or "(empty)",
        "```",
        "",
        "### Tool calls",
        "",
        *_tool_calls_body(result),
        "",
        "score:",
        "",
    ]


def _tool_calls_body(result: CaseResult) -> list[str]:
    if not result.tool_calls:
        return ["(none)"]
    return [
        "```json",
        json.dumps(result.tool_calls, ensure_ascii=False, indent=2),
        "```",
    ]


def _percentile(values: list[float], pct: int) -> str:
    if not values:
        return "n/a"
    if len(values) == 1:
        return f"{values[0]:.1f}"
    try:
        value = statistics.quantiles(values, n=100)[pct - 1]
    except (statistics.StatisticsError, IndexError):
        value = sorted(values)[min(len(values) - 1, int(len(values) * pct / 100))]
    return f"{value:.1f}"
