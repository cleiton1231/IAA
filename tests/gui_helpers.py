"""Synthetic fixtures for local GUI reader tests."""

import sqlite3
from pathlib import Path

from bancada.models import Run
from bancada.store import SCHEMA, save_run


def make_run(run_id: str = "a", model_id: str = "model-a") -> Run:
    return Run(
        id=run_id,
        model_id=model_id,
        endpoint="http://127.0.0.1:8080/v1",
        suite_versions={"skepticism": 1},
        seed=42,
    )


def make_db(tmp_path: Path, runs: list[Run]) -> Path:
    db = tmp_path / "runs.sqlite"
    if not runs:
        with sqlite3.connect(db) as conn:
            conn.executescript(SCHEMA)
    for run in runs:
        save_run(db, run)
    return db
