"""Render a Markdown judge packet from a stored run."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from typing import Any

from bancada.loader import DEFAULT_CATEGORIES
from bancada.models import CaseResult, Run

STANDARD_CATEGORIES = ["codigo", "agentico", "ceticismo", "humanas"]


def _get_category(result: CaseResult) -> str:
    if result.category:
        return result.category
    return DEFAULT_CATEGORIES.get(result.suite, "outros")


def render_packet(run: Run) -> str:
    latencies = [item.total_ms for item in run.results if item.error is None]
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    lines = [
        f"# Bancada packet {run.id}",
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

    # Group results by category
    by_category: dict[str, list[CaseResult]] = defaultdict(list)
    for result in run.results:
        cat = _get_category(result)
        by_category[cat].append(result)

    # All categories to show in summary table
    seen_cats = set(by_category.keys())
    table_cats = [c for c in STANDARD_CATEGORIES if c in seen_cats or not seen_cats]
    # Add any extra categories not in STANDARD_CATEGORIES
    for c in by_category:
        if c not in table_cats:
            table_cats.append(c)
    if not table_cats:
        table_cats = list(STANDARD_CATEGORIES)

    # Machine summary table
    lines.extend(
        [
            "## Resumo máquina",
            "",
            "| Categoria | n | machine_pass | p50_ms |",
            "|---|---|---|---|",
        ]
    )

    tot_cases = len(run.results)
    tot_pass = sum(
        1 for r in run.results if r.checks and all(c.ok for c in r.checks) and not r.error
    )
    tot_pct = (tot_pass / tot_cases * 100) if tot_cases else 0.0

    for cat in table_cats:
        cat_results = by_category.get(cat, [])
        n = len(cat_results)
        if n > 0:
            n_pass = sum(
                1 for r in cat_results if r.checks and all(c.ok for c in r.checks) and not r.error
            )
            pct = n_pass / n * 100
            pass_str = f"{n_pass}/{n} ({pct:.0f}%)"
            cat_lats = [r.total_ms for r in cat_results if r.error is None]
            cat_p50 = _percentile(cat_lats, 50)
        else:
            pass_str = "-"
            cat_p50 = "-"
        lines.append(f"| {cat} | {n} | {pass_str} | {cat_p50} |")

    tot_pass_str = f"{tot_pass}/{tot_cases} ({tot_pct:.0f}%)" if tot_cases else "-"
    lines.append(f"| **total** | {tot_cases} | {tot_pass_str} | {p50} |")
    lines.append("")

    # Sections by category
    for cat in table_cats:
        cat_results = by_category.get(cat, [])
        if not cat_results:
            continue
        lines.extend(
            [
                f"## {cat}",
                "",
            ]
        )
        for result in cat_results:
            lines.extend(_case_block(result))

    template: dict[str, Any] = {
        "run_id": run.id,
        "judge": "grok-chat",
        "cases": [
            {"id": item.case_id, "score": None, "max": 3, "reason": ""}
            for item in run.results
        ],
    }
    lines.extend(
        [
            "## JSON do juiz",
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
    block = [
        f"### {result.case_id}",
        "",
        f"- source: {result.source}",
        f"- suite: {result.suite}",
        f"- category: {_get_category(result)}",
        f"- total_ms: {result.total_ms:.1f}",
        f"- error: {result.error or 'none'}",
        f"- machine_checks: {checks}",
        f"- stance: `{gab.stance.value}`",
        f"- must_cover: {gab.must_cover}",
        f"- must_not: {gab.must_not}",
        f"- gabarito_notes: {gab.notes or '(none)'}",
        "",
        "#### Prompt",
        "",
        "```",
        result.prompt.rstrip(),
        "```",
        "",
    ]

    if result.turn1_reply is not None or result.turn1_tool_calls is not None:
        block.extend(
            [
                "#### Turno 1 (Assistant)",
                "",
                "```",
                (result.turn1_reply or "").rstrip() or "(empty)",
                "```",
                "",
                "#### Turno 1 (Tool Calls)",
                "",
                *_format_tool_calls(result.turn1_tool_calls),
                "",
                "#### Turno 2 Reply",
                "",
                "```",
                (result.reply or "").rstrip() or "(empty)",
                "```",
                "",
            ]
        )
    else:
        block.extend(
            [
                "#### Reply",
                "",
                "```",
                (result.reply or "").rstrip() or "(empty)",
                "```",
                "",
            ]
        )

    block.extend(
        [
            "### Tool calls",
            "",
            *_format_tool_calls(result.tool_calls),
            "",
            "score:",
            "",
        ]
    )
    return block


def _format_tool_calls(tool_calls: list[dict[str, Any]] | None) -> list[str]:
    if not tool_calls:
        return ["(none)"]
    return [
        "```json",
        json.dumps(tool_calls, ensure_ascii=False, indent=2),
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
