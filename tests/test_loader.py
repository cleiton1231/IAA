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
    prompt: a
    gabarito:
      stance: accept_true_control
  - id: code.same
    source: manual
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


def test_invalid_stance_fails(tmp_path: Path) -> None:
    path = tmp_path / "stance.yaml"
    path.write_text(
        """
version: 1
suite: skepticism
cases:
  - id: sk.bad
    source: manual
    prompt: x
    gabarito:
      stance: vibes
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="stance"):
        load_suite(path)
