"""Load and validate YAML suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from bancada.models import Case, Suite


def load_suite(path: Path | str) -> Suite:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: suite YAML must be a mapping")

    name = raw.get("suite")
    if not name:
        raise ValueError(f"{path}: missing suite name")

    cases_raw = raw.get("cases")
    if not cases_raw:
        raise ValueError(f"{path}: empty suite")

    cases: list[Case] = []
    seen: set[str] = set()
    for item in cases_raw:
        if not isinstance(item, dict):
            raise ValueError(f"{path}: case must be a mapping")
        if "gabarito" not in item:
            raise ValueError(f"{path}: case {item.get('id', '?')} missing gabarito")
        try:
            case = Case.model_validate({**item, "suite": item.get("suite") or name})
        except ValidationError as exc:
            _reraise_stance(path, item, exc)
            raise ValueError(f"{path}: invalid case {item.get('id', '?')}: {exc}") from exc
        if case.id in seen:
            raise ValueError(f"{path}: duplicate case id {case.id}")
        seen.add(case.id)
        cases.append(case)

    version = int(raw.get("version", 1))
    return Suite(name=str(name), version=version, cases=cases)


def _reraise_stance(path: Path, item: dict[str, Any], exc: ValidationError) -> None:
    for err in exc.errors():
        loc = err.get("loc") or ()
        if "stance" in loc:
            raise ValueError(f"{path}: invalid stance in {item.get('id', '?')}") from exc
