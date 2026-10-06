"""SQLite store round-trips a run and later judge scores."""

from pathlib import Path

import pytest

from bancada.models import CaseResult, CheckOutcome, Gabarito, Run, Stance
from bancada.store import list_runs, load_run, save_run, save_scores


def _resume_config(**overrides: object):
    import bancada.store as store

    config_type = getattr(store, "ResumeConfig", None)
    assert config_type is not None, "store.ResumeConfig must be defined"
    values = {
        "endpoint": "http://127.0.0.1:8080/v1",
        "seed": 42,
        "temperature": 0.0,
        "max_tokens": 512,
        "timeout": 60.0,
        "harness": "direct",
    }
    values.update(overrides)
    return config_type(**values)


def _run() -> Run:
    return Run(
        id="abc123",
        model_id="toy-model",
        endpoint="http://127.0.0.1:8080/v1",
        suite_versions={"code": 1},
        results=[
            CaseResult(
                case_id="code.reverse",
                suite="code",
                source="manual",
                prompt="escreva reverse",
                reply="ok",
                checks=[CheckOutcome(type="not_empty", ok=True)],
                total_ms=12.5,
                gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
            )
        ],
    )


def test_save_and_load_run(tmp_path: Path) -> None:
    db = tmp_path / "bancada.sqlite"
    run = _run()
    run.max_tokens = 512
    run.timeout = 45.0
    run.temperature = 0.7
    run.seed = 42
    save_run(db, run)
    loaded = load_run(db, "abc123")
    assert loaded is not None
    assert loaded.model_id == "toy-model"
    assert loaded.max_tokens == 512
    assert loaded.timeout == 45.0
    assert loaded.temperature == 0.7
    assert loaded.seed == 42
    assert loaded.results[0].case_id == "code.reverse"
    assert loaded.results[0].checks[0].ok is True
    assert loaded.results[0].gabarito.stance == Stance.ACCEPT_TRUE_CONTROL


def test_find_resumable_run(tmp_path: Path) -> None:
    from bancada.store import find_resumable_run

    db = tmp_path / "bancada.sqlite"
    run = _run()
    save_run(db, run)

    # Match by model and suite_versions
    found = find_resumable_run(db, "toy-model", {"code": 1})
    assert found is not None
    assert found.id == "abc123"

    # Mismatch model
    assert find_resumable_run(db, "other-model", {"code": 1}) is None

    # Mismatch version
    assert find_resumable_run(db, "toy-model", {"code": 2}) is None


def test_run_suite_versions_round_trip_with_manual_and_imported_keys(tmp_path: Path) -> None:
    db = tmp_path / "bancada.sqlite"
    run = _run()
    run.suite_versions = {"code": 5, "imported/code": 1}
    save_run(db, run)

    loaded = load_run(db, run.id)

    assert loaded is not None
    assert loaded.suite_versions == {"code": 5, "imported/code": 1}


@pytest.mark.parametrize(
    "field,value",
    [
        ("endpoint", "http://127.0.0.1:8081/v1"),
        ("seed", 43),
        ("temperature", 0.5),
        ("max_tokens", 256),
        ("timeout", 30.0),
        ("harness", "pi"),
    ],
)
def test_resume_requires_requested_configuration(
    tmp_path: Path, field: str, value: object
) -> None:
    from bancada.store import find_resumable_run

    db = tmp_path / "bancada.sqlite"
    run = _run()
    run.endpoint = "http://127.0.0.1:8080/v1"
    run.seed = 42
    run.temperature = 0.0
    run.max_tokens = 512
    run.timeout = 60.0
    run.harness = "direct"
    setattr(run, field, value)
    save_run(db, run)
    expected = _resume_config()

    assert (
        find_resumable_run(
            db, "toy-model", {"code": 1}, config=expected
        )
        is None
    )


def test_resume_requires_exact_version_map_and_raw_harness(tmp_path: Path) -> None:
    import sqlite3

    from bancada.store import find_resumable_run

    db = tmp_path / "bancada.sqlite"
    run = _run()
    run.endpoint = "http://127.0.0.1:8080/v1"
    run.seed = 42
    run.temperature = 0.0
    run.max_tokens = 512
    run.timeout = 60.0
    save_run(db, run)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE runs SET harness = NULL WHERE id = ?", (run.id,))
    expected = _resume_config()

    assert find_resumable_run(db, "toy-model", {"code": 1}, config=expected) is None
    assert (
        find_resumable_run(
            db, "toy-model", {"code": 1, "imported/code": 1}, config=expected
        )
        is None
    )


def test_resume_returns_compatible_incomplete_run_and_retries_errors(tmp_path: Path) -> None:
    from bancada.store import find_resumable_run

    db = tmp_path / "bancada.sqlite"
    run = _run()
    run.endpoint = "http://127.0.0.1:8080/v1"
    run.seed = 42
    run.temperature = 0.0
    run.max_tokens = 512
    run.timeout = 60.0
    run.results[0].error = "temporary endpoint error"
    save_run(db, run)
    expected = _resume_config()

    found = find_resumable_run(
        db,
        "toy-model",
        {"code": 1},
        expected_case_ids={"code.reverse", "code.second"},
        config=expected,
    )
    assert found is not None
    assert found.id == run.id
    assert find_resumable_run(
        db,
        "toy-model",
        {"code": 1},
        expected_case_ids={"code.reverse"},
        config=expected,
    ) is not None
    run.results[0].error = None
    save_run(db, run)
    assert find_resumable_run(
        db,
        "toy-model",
        {"code": 1},
        expected_case_ids={"code.reverse"},
        config=expected,
    ) is None


def test_explicit_resume_id_obeys_configuration_filters(tmp_path: Path) -> None:
    from bancada.store import find_resumable_run

    db = tmp_path / "bancada.sqlite"
    run = _run()
    run.endpoint = "http://127.0.0.1:8080/v1"
    run.seed = 42
    run.temperature = 0.0
    run.max_tokens = 512
    run.timeout = 60.0
    save_run(db, run)
    expected = _resume_config()

    assert find_resumable_run(
        db, "toy-model", {"code": 1}, run_id=run.id, config=expected
    ) is not None
    assert find_resumable_run(
        db,
        "toy-model",
        {"code": 1, "imported/code": 1},
        run_id=run.id,
        config=expected,
    ) is None


def test_list_runs_newest_first(tmp_path: Path) -> None:
    db = tmp_path / "bancada.sqlite"
    first = _run()
    second = _run()
    second.id = "def456"
    second.model_id = "other"
    save_run(db, first)
    save_run(db, second)
    ids = [item.id for item in list_runs(db)]
    assert ids == ["def456", "abc123"]


def test_load_missing_run_returns_none(tmp_path: Path) -> None:
    db = tmp_path / "bancada.sqlite"
    save_run(db, _run())
    assert load_run(db, "nope") is None


def test_save_scores_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "bancada.sqlite"
    save_run(db, _run())
    save_scores(
        db,
        "abc123",
        {"judge": "grok-chat", "cases": [{"id": "code.reverse", "score": 3, "max": 3}]},
    )
    loaded = load_run(db, "abc123")
    assert loaded is not None
    assert loaded.judge_scores is not None
    assert loaded.judge_scores["cases"][0]["score"] == 3
