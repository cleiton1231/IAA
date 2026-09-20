"""ENEM aggregate + max_tokens resolution + ingest merge."""

from __future__ import annotations

from bancada.aggregate import format_enem_lines, summarize_run
from bancada.cli import _merge_scores
from bancada.models import (
    Case,
    CaseResult,
    CheckOutcome,
    Difficulty,
    Gabarito,
    Run,
    Stance,
)
from bancada.runner import effective_max_tokens


def _result(
    case_id: str,
    *,
    ok: bool,
    difficulty: Difficulty,
    category: str = "codigo",
    suite: str = "code",
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        suite=suite,
        category=category,
        source="manual",
        prompt="x",
        reply="y",
        checks=[CheckOutcome(type="not_empty", ok=ok)],
        fail_class="ok" if ok else "model",
        fail_reason="" if ok else "stance",
        difficulty=difficulty,
        gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
    )


def test_enem_fail_facil_hurts_more_than_dificil() -> None:
    run = Run(
        id="r1",
        model_id="m",
        endpoint="http://x",
        results=[
            _result("f1", ok=False, difficulty=Difficulty.FACIL),
            _result("d1", ok=True, difficulty=Difficulty.DIFICIL),
            _result("d2", ok=True, difficulty=Difficulty.DIFICIL),
        ],
    )
    summary = summarize_run(run)
    # max = 3 + 2 + 2 = 7; earned = 0 + 2 + 2 = 4
    assert summary["enem_max"] == 7
    assert summary["enem_earned"] == 4
    assert summary["enem_score"] == round(4 / 7, 4)


def test_suspeito_flag_when_facil_weak_dificil_strong() -> None:
    results = [
        _result(f"f{i}", ok=False, difficulty=Difficulty.FACIL) for i in range(4)
    ] + [
        _result(f"d{i}", ok=True, difficulty=Difficulty.DIFICIL) for i in range(4)
    ]
    summary = summarize_run(
        Run(id="r", model_id="m", endpoint="e", results=results)
    )
    assert summary["suspeito"] is True
    lines = "\n".join(format_enem_lines(summary))
    assert "não zera enem_score" in lines


def test_resolve_max_tokens_case_vs_global_cap() -> None:
    case = Case(
        id="c",
        suite="code",
        prompt="p",
        gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
        difficulty=Difficulty.FACIL,
        max_tokens=384,
    )
    assert effective_max_tokens(case, 512) == 384
    assert effective_max_tokens(case, 256) == 256  # global ceiling
    bare = Case(
        id="t",
        suite="tools",
        prompt="p",
        gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
        difficulty=Difficulty.MEDIO,
    )
    assert effective_max_tokens(bare, None) == 256


def test_merge_scores_auto_plus_judge() -> None:
    auto = {
        "cases": [
            {"id": "a", "score": 3, "auto": True},
            {"id": "b", "score": 0, "auto": True},
        ]
    }
    judge = {"cases": [{"id": "b", "score": 2, "reason": "partial"}]}
    merged = _merge_scores(auto, judge)
    by = {c["id"]: c for c in merged["cases"]}
    assert by["a"]["score"] == 3
    assert by["b"]["score"] == 2
    assert merged["auto_merged"] is True
