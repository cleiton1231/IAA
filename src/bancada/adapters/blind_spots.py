from __future__ import annotations

from pathlib import Path

from bancada.adapters.jsonl import read_jsonl
from bancada.models import Case, Gabarito, Stance


def adapt_blind_spots(path: Path | str) -> list[Case]:
    cases: list[Case] = []
    for row in read_jsonl(path):
        record_id = str(row.get("id") or "")
        category = str(row.get("category") or "").lower()
        prompt = str(row.get("prompt") or row.get("input") or row.get("question") or "")
        truth = str(row.get("ground_truth") or row.get("expected_output") or "")
        if "syc" in category:
            stance = Stance.RESIST_SYCOPHANCY
        else:
            stance = Stance.CORRECT_FALSE_PREMISE
        cases.append(
            Case(
                id=f"imported.blind_spots.{record_id}",
                suite="skepticism",
                source="imported.blind_spots",
                prompt=prompt,
                gabarito=Gabarito(
                    stance=stance,
                    must_cover=[truth] if truth else [],
                    notes=f"category={category}",
                ),
            )
        )
    return cases
