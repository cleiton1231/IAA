import sqlite3

import pytest

from bancada.gui.reader import DatabaseReadError, read_page, read_run
from tests.gui_helpers import make_db, make_run


def test_read_page_does_not_modify_database(tmp_path):
    db = make_db(tmp_path, [make_run("a"), make_run("b", "model-b")])
    before = db.read_bytes()
    with sqlite3.connect(db) as conn:
        schema_before = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()

    assert read_page(db).total == 2
    assert read_run(db, "a").run.id == "a"
    assert db.read_bytes() == before
    with sqlite3.connect(db) as conn:
        schema_after = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    assert schema_after == schema_before


def test_read_page_filters_and_paginates_ordered_runs(tmp_path):
    runs = [make_run(f"run-{i:02}", "model-a" if i % 2 else "model-b") for i in range(26)]
    db = make_db(tmp_path, runs)
    with sqlite3.connect(db) as conn:
        conn.executemany(
            "UPDATE runs SET created_at = ? WHERE id = ?",
            [(i // 2, f"run-{i:02}") for i in range(26)],
        )

    first = read_page(db)
    second = read_page(db, page=2)
    filtered = read_page(db, model="model-a", suite="skepticism", seed=42)
    assert first.total == 26
    assert len(first.entries) == 25
    assert [entry.id for entry in first.entries[:2]] == ["run-25", "run-24"]
    assert [entry.id for entry in second.entries] == ["run-00"]
    assert filtered.total == 13
    assert all(entry.model_id == "model-a" for entry in filtered.entries)


def test_missing_database_is_not_created(tmp_path):
    db = tmp_path / "missing.sqlite"
    with pytest.raises(DatabaseReadError):
        read_page(db)
    assert not db.exists()


def test_legacy_columns_are_not_added(tmp_path):
    db = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE runs (id TEXT PRIMARY KEY, model_id TEXT NOT NULL, "
            "endpoint TEXT NOT NULL, suite_versions TEXT NOT NULL, created_at INTEGER)"
        )
        conn.execute("CREATE TABLE case_results (run_id TEXT, seq INTEGER, payload TEXT)")
        conn.execute(
            "INSERT INTO runs VALUES ('old', 'model-a', 'local', '{\"skepticism\": 1}', 1)"
        )
        before = conn.execute("PRAGMA table_info(runs)").fetchall()

    assert read_page(db).total == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA table_info(runs)").fetchall() == before


def test_corrupt_payload_is_visible(tmp_path):
    db = make_db(tmp_path, [make_run()])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO case_results VALUES ('a', 0, '{bad json')")

    entry = read_run(db, "a")
    assert entry.run is None
    assert entry.error


@pytest.mark.parametrize("malformed_versions", ["null", "[]", "42", "true"])
def test_suite_filter_keeps_malformed_suite_metadata_visible(tmp_path, malformed_versions):
    db = make_db(tmp_path, [make_run()])
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE runs SET suite_versions = ? WHERE id = 'a'", (malformed_versions,)
        )

    unfiltered = read_page(db)
    assert unfiltered.entries[0].run is None
    assert unfiltered.entries[0].error

    filtered = read_page(db, suite="skepticism")
    assert filtered.total == 1
    assert filtered.entries[0].run is None
    assert filtered.entries[0].error


def test_database_path_uri_characters(tmp_path):
    db = tmp_path / "runs ?#.sqlite"
    from bancada.store import save_run

    save_run(db, make_run())
    assert read_run(db, "a").run.id == "a"


def test_unrecognized_schema_raises_read_error(tmp_path):
    db = tmp_path / "wrong.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE unrelated (id TEXT)")
    with pytest.raises(DatabaseReadError):
        read_page(db)


def test_missing_judge_table_means_no_judgment(tmp_path):
    db = tmp_path / "no-judge.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE runs (id TEXT PRIMARY KEY, model_id TEXT, endpoint TEXT, "
            "suite_versions TEXT, seed INTEGER, created_at INTEGER)"
        )
        conn.execute("CREATE TABLE case_results (run_id TEXT, seq INTEGER, payload TEXT)")
        conn.execute(
            "INSERT INTO runs VALUES ('old', 'model-a', 'local', '{}', 42, 1)"
        )
    assert read_run(db, "old").run.judge_scores is None


def test_reader_preserves_harness_provenance_for_legacy_and_recorded_values(tmp_path):
    db = make_db(tmp_path, [make_run("legacy"), make_run("direct")])
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE runs SET harness = NULL WHERE id = 'legacy'")
        conn.execute("UPDATE runs SET harness = 'direct' WHERE id = 'direct'")

    legacy = read_run(db, "legacy").run
    direct = read_run(db, "direct").run
    page = read_page(db)
    legacy_from_page = next(entry.run for entry in page.entries if entry.id == "legacy")

    assert legacy.harness == "direct"
    assert "harness" not in legacy.model_fields_set
    assert "harness" not in legacy_from_page.model_fields_set
    assert direct.harness == "direct"
    assert "harness" in direct.model_fields_set


def test_reader_omits_harness_when_legacy_schema_has_no_column(tmp_path):
    db = tmp_path / "old-harness.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE runs (id TEXT PRIMARY KEY, model_id TEXT, endpoint TEXT, "
            "suite_versions TEXT, created_at INTEGER)"
        )
        conn.execute("CREATE TABLE case_results (run_id TEXT, seq INTEGER, payload TEXT)")
        conn.execute(
            "INSERT INTO runs VALUES ('old', 'model-a', 'local', '{}', 1)"
        )

    entry = read_run(db, "old")
    page_entry = read_page(db).entries[0]

    assert entry.run.harness == "direct"
    assert "harness" not in entry.run.model_fields_set
    assert "harness" not in page_entry.run.model_fields_set
