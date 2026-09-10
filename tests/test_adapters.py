"""Adapters turn tiny public-style records into Bancada cases."""

from pathlib import Path

from bancada.adapters.bfcl import adapt_bfcl
from bancada.adapters.blind_spots import adapt_blind_spots
from bancada.adapters.falseqa import adapt_falseqa
from bancada.adapters.humaneval import adapt_humaneval
from bancada.adapters.truthfulqa import adapt_truthfulqa
from bancada.models import Stance

FIXTURES = Path(__file__).parent / "fixtures"


def test_humaneval_case_has_python_test_and_stable_id() -> None:
    cases = adapt_humaneval(FIXTURES / "humaneval.jsonl")
    by_id = {c.id: c for c in cases}
    case = by_id["imported.humaneval.HumanEval/0"]
    assert case.suite == "code"
    assert "def add" in case.prompt
    py = [c for c in case.machine_checks if c.type == "python_test"][0]
    assert "check(add)" in (py.source or "")


def test_bfcl_simple_expects_tool_and_irrelevance_expects_none() -> None:
    cases = adapt_bfcl(FIXTURES / "bfcl.jsonl")
    by_id = {c.id: c for c in cases}
    simple = by_id["imported.bfcl.simple_0"]
    assert simple.machine_checks[0].type == "tool_name"
    assert simple.machine_checks[0].expected == "cron"
    assert simple.tools is not None
    irr = by_id["imported.bfcl.irr_0"]
    assert irr.machine_checks[0].expected is None


def test_truthfulqa_fills_must_cover() -> None:
    cases = adapt_truthfulqa(FIXTURES / "truthfulqa.jsonl")
    assert cases[0].gabarito.must_cover == ["No"]
    assert cases[0].gabarito.must_not == ["Yes"]
    assert cases[0].gabarito.stance == Stance.CORRECT_FALSE_PREMISE


def test_falseqa_uses_correct_false_premise() -> None:
    cases = adapt_falseqa(FIXTURES / "falseqa.jsonl")
    assert cases[0].id.startswith("imported.falseqa.")
    assert cases[0].gabarito.stance == Stance.CORRECT_FALSE_PREMISE


def test_blind_spots_sycophancy_stance() -> None:
    cases = adapt_blind_spots(FIXTURES / "blind_spots.jsonl")
    by_id = {c.id: c for c in cases}
    assert by_id["imported.blind_spots.syc_1"].gabarito.stance == Stance.RESIST_SYCOPHANCY
    assert by_id["imported.blind_spots.fb_1"].gabarito.stance == Stance.CORRECT_FALSE_PREMISE
