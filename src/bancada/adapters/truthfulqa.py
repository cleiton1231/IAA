from __future__ import annotations

import csv
from pathlib import Path

from bancada.adapters.jsonl import read_jsonl
from bancada.models import Case, Gabarito, Stance


def adapt_truthfulqa(path: Path | str) -> list[Case]:
    path = Path(path)
    rows = _csv_rows(path) if path.suffix.lower() == ".csv" else read_jsonl(path)
    cases: list[Case] = []
    for index, row in enumerate(rows):
        question = str(row.get("question") or row.get("Question") or "")
        correct = _answers(row.get("correct_answers") or row.get("Correct Answers"))
        incorrect = _answers(row.get("incorrect_answers") or row.get("Incorrect Answers"))
        slug = f"{index}"
        cases.append(
            Case(
                id=f"imported.truthfulqa.{slug}",
                suite="skepticism",
                source="imported.truthfulqa",
                prompt=question,
                gabarito=Gabarito(
                    stance=Stance.CORRECT_FALSE_PREMISE,
                    must_cover=correct[:3],
                    must_not=incorrect[:3],
                    notes="Do not repeat the popular misconception.",
                ),
            )
        )
    return cases


def _answers(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(";") if part.strip()][:8]


def _csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
