from __future__ import annotations

import ast
import csv
from pathlib import Path

from bancada.adapters.jsonl import read_jsonl
from bancada.models import Case, Gabarito, Stance


def adapt_falseqa(path: Path | str) -> list[Case]:
    path = Path(path)
    rows = _csv_rows(path) if path.suffix.lower() == ".csv" else read_jsonl(path)
    cases: list[Case] = []
    for index, row in enumerate(rows):
        question = str(row.get("question") or row.get("prompt") or "")
        explanation = str(row.get("explanation") or "")
        answers = _falseqa_answers(row.get("answer"))
        label = str(row.get("label", "1"))
        stance = Stance.CORRECT_FALSE_PREMISE if label != "0" else Stance.ACCEPT_TRUE_CONTROL
        notes = (
            "The question contains a false premise; correct it."
            if stance == Stance.CORRECT_FALSE_PREMISE
            else "True-premise control; answer the question."
        )
        cases.append(
            Case(
                id=f"imported.falseqa.{index}",
                suite="skepticism",
                source="imported.falseqa",
                prompt=question,
                gabarito=Gabarito(
                    stance=stance,
                    must_cover=([explanation] if explanation else []) + answers[:2],
                    notes=notes,
                ),
            )
        )
    return cases


def _falseqa_answers(raw: object) -> list[str]:
    if raw is None:
        return []
    text = str(raw).strip()
    if text.startswith("["):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
        except (ValueError, SyntaxError):
            return [text]
    return [text] if text else []


def _csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
