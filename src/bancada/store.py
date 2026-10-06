"""SQLite persistence for runs, case results, and ingested judge scores."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bancada.models import Run


@dataclass(frozen=True)
class ResumeConfig:
    endpoint: str
    seed: int
    temperature: float
    max_tokens: int
    timeout: float
    harness: str

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    suite_versions TEXT NOT NULL,
    max_tokens INTEGER,
    timeout REAL,
    temperature REAL,
    seed INTEGER,
    harness TEXT,
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
        ("seed", "INTEGER"),
        ("harness", "TEXT"),
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
            (id, model_id, endpoint, suite_versions, max_tokens,
             timeout, temperature, seed, harness)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                run.id,
                run.model_id,
                run.endpoint,
                json.dumps(run.suite_versions),
                run.max_tokens,
                run.timeout,
                run.temperature,
                run.seed,
                run.harness,
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
            SELECT id, model_id, endpoint, suite_versions, max_tokens,
                   timeout, temperature, seed, harness
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
            seed=row[7],
            harness=row[8] or "direct",
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
    *,
    config: ResumeConfig | None = None,
) -> Run | None:
    def compatible(cand: Run) -> bool:
        if cand.model_id != model_id or cand.suite_versions != suite_versions:
            return False
        if config is None:
            return True
        conn = _connect(Path(path))
        try:
            row = conn.execute(
                """SELECT endpoint, seed, temperature, max_tokens, timeout, harness
                   FROM runs WHERE id = ?""",
                (cand.id,),
            ).fetchone()
        finally:
            conn.close()
        return row == (
            config.endpoint,
            config.seed,
            config.temperature,
            config.max_tokens,
            config.timeout,
            config.harness,
        )

    if run_id:
        cand = load_run(path, run_id)
        if cand and compatible(cand):
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
            if v_dict != suite_versions:
                continue
            cand = load_run(path, cand_id)
            if cand and compatible(cand):
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


def merge_scores(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge auto + judge cases into a single cases list (judge overrides auto by id)."""
    by_id: dict[str, dict[str, Any]] = {}
    for item in payload.get("auto") or []:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = dict(item)
    for item in payload.get("cases") or []:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = dict(item)
    merged = dict(payload)
    if by_id:
        merged["cases"] = list(by_id.values())
    return merged


def save_scores(path: Path | str, run_id: str, scores: dict[str, Any]) -> None:
    conn = _connect(Path(path))
    try:
        exists = conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone()
        if exists is None:
            raise ValueError(f"unknown run {run_id}")
        merged = merge_scores(scores)
        conn.execute(
            "INSERT OR REPLACE INTO judge_scores (run_id, payload) VALUES (?,?)",
            (run_id, json.dumps(merged)),
        )
        conn.commit()
    finally:
        conn.close()
