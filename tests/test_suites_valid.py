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


RETIRED = {
    "skepticism.dois-mais-dois",
    "skepticism.python3-controle",
    "skepticism.sol-orbita",
    "skepticism.llama-h100",
    "code.reverse",
    "code.clamp",
    "code.none-safe",
    "code.palindrome",
    "code.off-by-one",
    "tools.aritmetica-sem-tool",
    "tools.cron-nao-exec",
    "obsidian.headings",
    "obsidian.flashcards-2",
}

SIGNAL = {
    "tools.refuse-force-push",
    "tools.refuse-curl-pipe",
    "tools.refuse-chmod",
    "skepticism.notes-contradict",
    "skepticism.contradict-short",
    "skepticism.pedir-fonte",
    "skepticism.um-mais-um",
    "skepticism.brasilia-controle",
    "skepticism.agua-ferve",
}


def test_manual_suite_versions_and_signal_cases() -> None:
    ids = set()
    versions = {}
    for name in MANUAL:
        suite = load_suite(ROOT / f"{name}.yaml")
        versions[name] = suite.version
        ids.update(case.id for case in suite.cases)
    assert versions == {"code": 6, "obsidian": 6, "tools": 7, "skepticism": 5}
    assert RETIRED.isdisjoint(ids)
    assert SIGNAL <= ids


def test_um_mais_um_accepts_dois() -> None:
    from bancada.scorers import run_checks

    suite = load_suite(ROOT / "skepticism.yaml")
    case = next(c for c in suite.cases if c.id == "skepticism.um-mais-um")
    reply = "Não, não concordo. A soma de um mais um resulta necessariamente em dois."
    assert all(item.ok for item in run_checks(reply, case.machine_checks))


def test_code_bug_prompts_do_not_name_the_fix() -> None:
    suite = load_suite(ROOT / "code.yaml")
    by_id = {case.id: case.prompt for case in suite.cases}
    forbidden = {
        "code.bug-fstring": "f-string",
        "code.bug-tz-naive": "timezone.utc",
        "code.bug-re-greedy": "não-gulosa",
        "code.bug-twomodule": "nome correto",
        "code.bug-none-is": "is None",
        "code.bug-sort-dict": "parâmetro `key`",
        "code.bug-shadow": "renomeando",
        "code.bug-path-join": "pathlib",
    }
    for case_id, needle in forbidden.items():
        assert needle not in by_id[case_id]
        assert next(c for c in suite.cases if c.id == case_id).max_tokens == 256


def test_imported_suites_optional() -> None:
    imported = ROOT / "imported"
    yaml_files = list(imported.glob("*.yaml")) if imported.exists() else []
    for path in yaml_files:
        suite = load_suite(path)
        ids = [case.id for case in suite.cases]
        assert len(ids) == len(set(ids))
