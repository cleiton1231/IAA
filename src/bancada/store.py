"""SQLite persistence for runs, case results, and ingested judge scores."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from bancada.models import Run

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    suite_versions TEXT NOT NULL,
    max_tokens INTEGER,
    timeout REAL,
    temperature REAL,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS case_results (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, seq),
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
CREATE TABLE IF NOT EXISTS judge_scores (
    run_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    cursor = conn.execute("PRAGMA table_info(runs)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    for col, col_type in [
        ("max_tokens", "INTEGER"),
        ("timeout", "REAL"),
        ("temperature", "REAL"),
    ]:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {col_type}")
    return conn


def save_run(path: Path | str, run: Run) -> None:
    conn = _connect(Path(path))
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs
            (id, model_id, endpoint, suite_versions, max_tokens, timeout, temperature)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                run.id,
                run.model_id,
                run.endpoint,
                json.dumps(run.suite_versions),
                run.max_tokens,
                run.timeout,
                run.temperature,
            ),
        )
        conn.execute("DELETE FROM case_results WHERE run_id = ?", (run.id,))
        for seq, result in enumerate(run.results):
            conn.execute(
                "INSERT INTO case_results (run_id, seq, payload) VALUES (?,?,?)",
                (run.id, seq, result.model_dump_json()),
            )
        conn.commit()
    finally:
        conn.close()


def load_run(path: Path | str, run_id: str) -> Run | None:
    conn = _connect(Path(path))
    try:
        row = conn.execute(
            """
            SELECT id, model_id, endpoint, suite_versions, max_tokens, timeout, temperature
            FROM runs WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        payloads = conn.execute(
            "SELECT payload FROM case_results WHERE run_id = ? ORDER BY seq",
            (run_id,),
        ).fetchall()
        score_row = conn.execute(
            "SELECT payload FROM judge_scores WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        run = Run(
            id=row[0],
            model_id=row[1],
            endpoint=row[2],
            suite_versions=json.loads(row[3]),
            max_tokens=row[4],
            timeout=row[5],
            temperature=row[6],
            results=[json.loads(item[0]) for item in payloads],
            judge_scores=json.loads(score_row[0]) if score_row else None,
        )
        return run
    finally:
        conn.close()


def find_resumable_run(
    path: Path | str,
    model_id: str,
    suite_versions: dict[str, int],
    run_id: str | None = None,
    expected_case_ids: list[str] | set[str] | None = None,
) -> Run | None:
    if run_id:
        cand = load_run(path, run_id)
        if cand and cand.model_id == model_id:
            if all(cand.suite_versions.get(k) == v for k, v in suite_versions.items()):
                if expected_case_ids:
                    done = {r.case_id for r in cand.results if not r.error}
                    if set(expected_case_ids).issubset(done):
                        return None
                return cand
        return None

    conn = _connect(Path(path))
    try:
        query = (
            "SELECT id, suite_versions FROM runs "
            "WHERE model_id = ? ORDER BY created_at DESC, id DESC"
        )
        rows = conn.execute(query, (model_id,)).fetchall()
        for cand_id, versions_json in rows:
            try:
                v_dict = json.loads(versions_json)
            except Exception:
                continue
            if all(v_dict.get(k) == v for k, v in suite_versions.items()):
                cand = load_run(path, cand_id)
                if cand:
                    if expected_case_ids:
                        done = {r.case_id for r in cand.results if not r.error}
                        if set(expected_case_ids).issubset(done):
                            continue
                    return cand
        return None
    finally:
        conn.close()


def list_runs(path: Path | str) -> list[Run]:
    conn = _connect(Path(path))
    try:
        rows = conn.execute(
            "SELECT id FROM runs ORDER BY created_at DESC, id DESC"
        ).fetchall()
        runs = []
        for (run_id,) in rows:
            loaded = load_run(path, run_id)
            if loaded is not None:
                runs.append(loaded)
        return runs
    finally:
        conn.close()


def save_scores(path: Path | str, run_id: str, scores: dict[str, Any]) -> None:
    conn = _connect(Path(path))
    try:
        exists = conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone()
        if exists is None:
            raise ValueError(f"unknown run {run_id}")
        conn.execute(
            "INSERT OR REPLACE INTO judge_scores (run_id, payload) VALUES (?,?)",
            (run_id, json.dumps(scores)),
        )
        conn.commit()
    finally:
        conn.close()
