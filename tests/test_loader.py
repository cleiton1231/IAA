"""YAML suite loader rejects bad files and keeps stable case ids."""

from pathlib import Path

import pytest

from bancada.loader import load_suite
from bancada.models import Stance


def test_valid_yaml_loads_case_fields(tmp_path: Path) -> None:
    path = tmp_path / "code.yaml"
    path.write_text(
        """
version: 1
suite: code
cases:
  - id: code.reverse
    source: manual
    difficulty: medio
    prompt: |
      Escreva reverse(s).
    gabarito:
      stance: accept_true_control
      must_cover: ["inverter"]
      notes: Função pura.
    machine_checks:
      - type: python_test
        source: |
          assert reverse("ab") == "ba"
""",
        encoding="utf-8",
    )
    suite = load_suite(path)
    assert suite.name == "code"
    assert suite.version == 1
    assert len(suite.cases) == 1
    case = suite.cases[0]
    assert case.id == "code.reverse"
    assert case.source == "manual"
    assert "reverse" in case.prompt
    assert case.gabarito.stance == Stance.ACCEPT_TRUE_CONTROL
    assert case.machine_checks[0].type == "python_test"


def test_yaml_without_gabarito_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
version: 1
suite: code
cases:
  - id: code.missing
    source: manual
    difficulty: medio
    prompt: oi
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="gabarito"):
        load_suite(path)


def test_duplicate_ids_fail(tmp_path: Path) -> None:
    path = tmp_path / "dup.yaml"
    path.write_text(
        """
version: 1
suite: code
cases:
  - id: code.same
    source: manual
    difficulty: medio
    prompt: a
    gabarito:
      stance: accept_true_control
  - id: code.same
    source: manual
    difficulty: medio
    prompt: b
    gabarito:
      stance: accept_true_control
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_suite(path)


def test_empty_suite_fails(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text(
        """
version: 1
suite: code
cases: []
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="empty"):
        load_suite(path)


def test_cap_applies_without_imported(tmp_path: Path) -> None:
    path = tmp_path / "code.yaml"
    path.write_text(
        """
version: 1
suite: code
cases:
  - id: code.a
    source: manual
    difficulty: medio
    prompt: a
    gabarito: {stance: accept_true_control}
  - id: code.b
    source: manual
    difficulty: medio
    prompt: b
    gabarito: {stance: accept_true_control}
  - id: code.c
    source: manual
    difficulty: medio
    prompt: c
    gabarito: {stance: accept_true_control}
""",
        encoding="utf-8",
    )
    from bancada.loader import load_named_suites

    suites = load_named_suites(tmp_path, ["code"], include_imported=False, cap=2)
    assert len(suites) == 1
    assert len(suites[0].cases) == 2


def test_imported_cap_does_not_slice_manual(tmp_path: Path) -> None:
    manual = tmp_path / "code.yaml"
    manual.write_text(
        """
version: 5
suite: code
cases:
  - id: code.a
    source: manual
    difficulty: medio
    prompt: a
    gabarito: {stance: accept_true_control}
  - id: code.b
    source: manual
    difficulty: medio
    prompt: b
    gabarito: {stance: accept_true_control}
""",
        encoding="utf-8",
    )
    imported_dir = tmp_path / "imported"
    imported_dir.mkdir()
    (imported_dir / "code.yaml").write_text(
        """
version: 1
suite: code
cases:
  - id: imported.a
    source: imported.humaneval
    difficulty: dificil
    prompt: a
    gabarito: {stance: accept_true_control}
  - id: imported.b
    source: imported.humaneval
    difficulty: dificil
    prompt: b
    gabarito: {stance: accept_true_control}
""",
        encoding="utf-8",
    )
    from bancada.loader import load_named_suites

    suites = load_named_suites(
        tmp_path, ["code"], include_imported=True, cap=None, imported_cap=1
    )
    assert [case.id for case in suites[0].cases] == ["code.a", "code.b"]
    assert [case.id for case in suites[1].cases] == ["imported.a"]


def test_invalid_stance_fails(tmp_path: Path) -> None:
    path = tmp_path / "stance.yaml"
    path.write_text(
        """
version: 1
suite: skepticism
cases:
  - id: sk.bad
    source: manual
    difficulty: medio
    prompt: x
    gabarito:
      stance: vibes
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="stance"):
        load_suite(path)


def test_all_repo_suites_yaml_valid_and_have_category() -> None:
    suites_dir = Path(__file__).resolve().parent.parent / "suites"
    yaml_files = list(suites_dir.glob("*.yaml"))
    assert len(yaml_files) >= 4

    valid_categories = {"codigo", "agentico", "ceticismo", "humanas"}
    for yf in yaml_files:
        suite = load_suite(yf)
        assert suite.category in valid_categories
        for case in suite.cases:
            assert case.category in valid_categories
