from __future__ import annotations

from pathlib import Path

from bancada.adapters.jsonl import read_jsonl
from bancada.models import Case, Gabarito, MachineCheck, Stance


def adapt_humaneval(path: Path | str) -> list[Case]:
    cases: list[Case] = []
    for row in read_jsonl(path):
        task_id = str(row.get("task_id") or row.get("id") or "")
        entry = str(row.get("entry_point") or "candidate")
        test = str(row.get("test") or "")
        prompt = str(row.get("prompt") or "")
        cases.append(
            Case(
                id=f"imported.humaneval.{task_id}",
                suite="code",
                source="imported.humaneval",
                prompt=(
                    "Complete the following Python function. "
                    "Reply with a single ```python fenced block containing the full function.\n\n"
                    f"{prompt}"
                ),
                gabarito=Gabarito(
                    stance=Stance.ACCEPT_TRUE_CONTROL,
                    notes=f"entry_point={entry}",
                ),
                machine_checks=[
                    MachineCheck(
                        type="python_test",
                        source=f"{test}\ncheck({entry})\n",
                    )
                ],
            )
        )
    return cases
