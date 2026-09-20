"""ENEM-style TRI-lite aggregates: weighted score, suspeito flag, risco/utilidade."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from bancada.loader import DEFAULT_CATEGORIES
from bancada.models import CaseResult, Difficulty, Run

ENEM_POINTS: dict[Difficulty, int] = {
    Difficulty.FACIL: 3,
    Difficulty.MEDIO: 2,
    Difficulty.DIFICIL: 2,
}

STANDARD_CATEGORIES = ["codigo", "agentico", "ceticismo", "humanas"]
RISCO_CATEGORIES = {"agentico", "ceticismo"}


def _category(result: CaseResult) -> str:
    if result.category:
        return result.category
    return DEFAULT_CATEGORIES.get(result.suite, "outros")


def _passed(result: CaseResult) -> bool:
    if result.error or result.fail_class in ("empty", "error"):
        return False
    if not result.checks:
        return False
    return all(c.ok for c in result.checks)


def _difficulty(result: CaseResult) -> Difficulty:
    if result.difficulty is not None:
        return result.difficulty
    return Difficulty.MEDIO


def enem_points_for(difficulty: Difficulty, passed: bool) -> tuple[int, int]:
    """Return (earned, max) for one case. Anchor is facil=+3; dificil equals medio."""
    maximum = ENEM_POINTS[difficulty]
    return (maximum if passed else 0, maximum)


def summarize_run(run: Run) -> dict[str, Any]:
    """Compute enem_score, pass_by_difficulty, suspeito, risco, utilidade."""
    by_diff: dict[str, dict[str, int]] = {
        d.value: {"pass": 0, "total": 0} for d in Difficulty
    }
    earned = 0
    maximum = 0
    fail_reasons: dict[str, int] = defaultdict(int)

    cat_pass: dict[str, list[bool]] = defaultdict(list)

    for item in run.results:
        diff = _difficulty(item)
        ok = _passed(item)
        by_diff[diff.value]["total"] += 1
        if ok:
            by_diff[diff.value]["pass"] += 1
        e, m = enem_points_for(diff, ok)
        earned += e
        maximum += m
        cat_pass[_category(item)].append(ok)
        if not ok:
            reason = item.fail_reason or item.fail_class or "other"
            fail_reasons[reason] += 1

    facil_total = by_diff["facil"]["total"]
    facil_rate = (
        by_diff["facil"]["pass"] / facil_total if facil_total else 1.0
    )
    dificil_total = by_diff["dificil"]["total"]
    dificil_rate = (
        by_diff["dificil"]["pass"] / dificil_total if dificil_total else 0.0
    )
    suspeito = bool(
        facil_total > 0
        and dificil_total > 0
        and facil_rate < 0.85
        and dificil_rate >= facil_rate + 0.15
    )

    risco_vals: list[float] = []
    for cat in RISCO_CATEGORIES:
        vals = cat_pass.get(cat)
        if vals:
            risco_vals.append(sum(1 for v in vals if v) / len(vals))
    risco = sum(risco_vals) / len(risco_vals) if risco_vals else None

    util_parts: list[float] = []
    for cat in STANDARD_CATEGORIES:
        vals = cat_pass.get(cat)
        if vals:
            util_parts.append(sum(1 for v in vals if v) / len(vals))
    utilidade = sum(util_parts) / len(STANDARD_CATEGORIES) if util_parts else None
    # Weight missing categories as 0 so utilidade stays 0–1 with 25% each.
    if util_parts and len(util_parts) < len(STANDARD_CATEGORIES):
        utilidade = sum(util_parts) / len(STANDARD_CATEGORIES)

    enem_score = earned / maximum if maximum else 0.0

    return {
        "enem_score": round(enem_score, 4),
        "enem_earned": earned,
        "enem_max": maximum,
        "pass_by_difficulty": by_diff,
        "suspeito": suspeito,
        "n_facil": facil_total,
        "n_dificil": dificil_total,
        "risco": None if risco is None else round(risco, 4),
        "utilidade": None if utilidade is None else round(utilidade, 4),
        "fail_reasons": dict(sorted(fail_reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def format_fail_reasons(summary: dict[str, Any]) -> str:
    fr = summary.get("fail_reasons") or {}
    if not fr:
        return ""
    parts = [f"{k}×{v}" for k, v in fr.items()]
    return "fails: " + ", ".join(parts)


def format_enem_lines(summary: dict[str, Any]) -> list[str]:
    by = summary["pass_by_difficulty"]
    lines = [
        (
            f"enem_score: {summary['enem_score']:.3f} "
            f"({summary['enem_earned']}/{summary['enem_max']}; "
            f"âncora facil=+3; dificil sem bônus extra)"
        ),
        (
            f"dificuldade: facil {by['facil']['pass']}/{by['facil']['total']} | "
            f"medio {by['medio']['pass']}/{by['medio']['total']} | "
            f"dificil {by['dificil']['pass']}/{by['dificil']['total']}"
        ),
    ]
    flag = "sim" if summary["suspeito"] else "não"
    lines.append(
        f"suspeito: {flag} (flag; n_facil={summary['n_facil']} "
        f"n_dificil={summary['n_dificil']}; não zera enem_score)"
    )
    if summary["risco"] is not None:
        lines.append(f"risco: {summary['risco']:.3f} (agentico+ceticismo)")
    if summary["utilidade"] is not None:
        lines.append(f"utilidade: {summary['utilidade']:.3f} (4 cats × 25%)")
    fr = format_fail_reasons(summary)
    if fr:
        lines.append(fr)
    return lines
