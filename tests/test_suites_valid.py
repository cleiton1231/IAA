"""Committed YAML suites load; imported files are optional."""

from pathlib import Path

import pytest

from bancada.loader import load_suite

ROOT = Path(__file__).resolve().parents[1] / "suites"
MANUAL = ("code", "obsidian", "tools", "skepticism")


@pytest.mark.parametrize("name", MANUAL)
def test_manual_suite_loads_with_unique_ids(name: str) -> None:
    suite = load_suite(ROOT / f"{name}.yaml")
    assert suite.name == name
    assert len(suite.cases) >= 8
    ids = [case.id for case in suite.cases]
    assert len(ids) == len(set(ids))
    assert all(case.gabarito is not None for case in suite.cases)


def test_skepticism_has_true_controls() -> None:
    suite = load_suite(ROOT / "skepticism.yaml")
    controls = [c for c in suite.cases if c.gabarito.stance.value == "accept_true_control"]
    assert len(controls) >= 2


def test_imported_suites_optional() -> None:
    imported = ROOT / "imported"
    yaml_files = list(imported.glob("*.yaml")) if imported.exists() else []
    for path in yaml_files:
        suite = load_suite(path)
        ids = [case.id for case in suite.cases]
        assert len(ids) == len(set(ids))
