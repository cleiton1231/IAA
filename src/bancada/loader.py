"""Load and validate YAML suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from bancada.models import Case, Suite


def load_named_suites(
    suites_dir: Path | str,
    names: list[str],
    include_imported: bool = False,
    cap: int | None = None,
) -> list[Suite]:
    root = Path(suites_dir)
    suites: list[Suite] = []
    for name in names:
        path = root / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"suite not found: {path}")
        suites.append(_apply_cap(load_suite(path), cap))
        if include_imported:
            imported = root / "imported" / f"{name}.yaml"
            if imported.exists():
                suites.append(_apply_cap(load_suite(imported), cap))
    return suites


DEFAULT_CATEGORIES: dict[str, str] = {
    "code": "codigo",
    "tools": "agentico",
    "skepticism": "ceticismo",
    "obsidian": "humanas",
    "humaneval": "codigo",
    "bfcl": "agentico",
    "truthfulqa": "ceticismo",
}


def _apply_cap(suite: Suite, cap: int | None) -> Suite:
    if cap is None or cap <= 0 or len(suite.cases) <= cap:
        return suite
    return Suite(
        name=suite.name,
        version=suite.version,
        category=suite.category,
        cases=suite.cases[:cap],
    )


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

    suite_name = str(name)
    suite_cat = str(raw.get("category") or DEFAULT_CATEGORIES.get(suite_name, suite_name))

    cases: list[Case] = []
    seen: set[str] = set()
    for item in cases_raw:
        if not isinstance(item, dict):
            raise ValueError(f"{path}: case must be a mapping")
        if "gabarito" not in item:
            raise ValueError(f"{path}: case {item.get('id', '?')} missing gabarito")
        case_suite = item.get("suite") or suite_name
        case_cat = item.get("category") or DEFAULT_CATEGORIES.get(case_suite, suite_cat)
        try:
            case = Case.model_validate(
                {
                    **item,
                    "suite": case_suite,
                    "category": case_cat,
                }
            )
        except ValidationError as exc:
            _reraise_stance(path, item, exc)
            raise ValueError(f"{path}: invalid case {item.get('id', '?')}: {exc}") from exc
        if case.id in seen:
            raise ValueError(f"{path}: duplicate case id {case.id}")
        seen.add(case.id)

        # Enhance machine checks with must_cover, must_not, and stance
        checks = list(case.machine_checks)
        for pattern in case.gabarito.must_cover:
            if not any(
                c.type == "must_cover" and (c.pattern == pattern or c.expected == pattern)
                for c in checks
            ):
                from bancada.models import MachineCheck

                checks.append(MachineCheck(type="must_cover", pattern=pattern))
        for pattern in case.gabarito.must_not:
            if not any(
                c.type == "must_not" and (c.pattern == pattern or c.expected == pattern)
                for c in checks
            ):
                from bancada.models import MachineCheck

                checks.append(MachineCheck(type="must_not", pattern=pattern))
        is_skeptic = case.suite == "skepticism" or case.category == "ceticismo"
        if is_skeptic and not any(c.type == "stance" for c in checks):
            from bancada.models import MachineCheck

            checks.append(MachineCheck(type="stance", expected=case.gabarito.stance.value))
        case.machine_checks = checks

        cases.append(case)

    version = int(raw.get("version", 1))
    return Suite(name=suite_name, version=version, category=suite_cat, cases=cases)



def _reraise_stance(path: Path, item: dict[str, Any], exc: ValidationError) -> None:
    for err in exc.errors():
        loc = err.get("loc") or ()
        if "stance" in loc:
            raise ValueError(f"{path}: invalid stance in {item.get('id', '?')}") from exc
