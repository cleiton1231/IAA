"""Read existing benchmark runs without changing their SQLite database."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bancada.models import Run


class DatabaseReadError(Exception):
    """The database cannot be read using a supported Bancada schema."""


@dataclass
class RunEntry:
    id: str
    model_id: str
    created_at: int | None
    run: Run | None
    error: str | None


@dataclass
class RunPage:
    entries: list[RunEntry]
    page: int
    total: int


def _connect(path: Path) -> sqlite3.Connection:
    try:
        uri = f"{path.expanduser().resolve().as_uri()}?mode=ro"
        return sqlite3.connect(uri, uri=True)
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise DatabaseReadError(f"Could not open database: {exc}") from exc


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _validate_schema(conn: sqlite3.Connection) -> tuple[set[str], set[str]]:
    tables = _tables(conn)
    if not {"runs", "case_results"}.issubset(tables):
        raise DatabaseReadError("Database is missing required runs or case_results tables")
    run_columns = _columns(conn, "runs")
    result_columns = _columns(conn, "case_results")
    if not {"id", "model_id"}.issubset(run_columns):
        raise DatabaseReadError("The runs table is missing required columns")
    if not {"run_id", "payload"}.issubset(result_columns):
        raise DatabaseReadError("The case_results table is missing required columns")
    return run_columns, result_columns


def _run_row(
    conn: sqlite3.Connection, run_id: str, run_columns: set[str]
) -> tuple[Any, ...] | None:
    wanted = [
        name
        for name in (
            "id",
            "model_id",
            "endpoint",
            "suite_versions",
            "max_tokens",
            "timeout",
            "temperature",
            "seed",
            "harness",
            "created_at",
        )
        if name in run_columns
    ]
    return conn.execute(
        f"SELECT {', '.join(wanted)} FROM runs WHERE id = ?", (run_id,)
    ).fetchone()


def _entry(
    conn: sqlite3.Connection,
    run_id: str,
    run_columns: set[str],
    result_columns: set[str],
    tables: set[str],
) -> RunEntry | None:
    columns = [
        name
        for name in (
            "id",
            "model_id",
            "endpoint",
            "suite_versions",
            "max_tokens",
            "timeout",
            "temperature",
            "seed",
            "harness",
            "created_at",
        )
        if name in run_columns
    ]
    try:
        row = _run_row(conn, run_id, run_columns)
        if row is None:
            return None
        metadata = dict(zip(columns, row, strict=True))
        created_at = metadata.get("created_at")
        entry = RunEntry(
            id=str(metadata["id"]),
            model_id=str(metadata["model_id"]),
            created_at=created_at,
            run=None,
            error=None,
        )
        result_order = "seq" if "seq" in result_columns else "rowid"
        payloads = conn.execute(
            f"SELECT payload FROM case_results WHERE run_id = ? ORDER BY {result_order}",
            (run_id,),
        ).fetchall()
        results = [json.loads(payload) for (payload,) in payloads]
        scores = None
        if "judge_scores" in tables:
            judge_columns = _columns(conn, "judge_scores")
            if {"run_id", "payload"}.issubset(judge_columns):
                score_row = conn.execute(
                    "SELECT payload FROM judge_scores WHERE run_id = ?", (run_id,)
                ).fetchone()
                if score_row is not None:
                    scores = json.loads(score_row[0])
        versions = metadata.get("suite_versions")
        run_data: dict[str, Any] = {
            "id": entry.id,
            "model_id": entry.model_id,
            "endpoint": metadata.get("endpoint") or "",
            "suite_versions": json.loads(versions) if versions else {},
            "results": results,
            "judge_scores": scores,
            "max_tokens": metadata.get("max_tokens"),
            "timeout": metadata.get("timeout"),
            "temperature": metadata.get("temperature"),
            "seed": metadata.get("seed"),
        }
        if metadata.get("harness") is not None:
            run_data["harness"] = metadata["harness"]
        run = Run(**run_data)
        entry.run = run
        return entry
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        metadata = _run_row(conn, run_id, run_columns)
        if metadata is None:
            return None
        base_columns = [
            name
            for name in (
                "id",
                "model_id",
                "endpoint",
                "suite_versions",
                "max_tokens",
                "timeout",
                "temperature",
                "seed",
                "harness",
                "created_at",
            )
            if name in run_columns
        ]
        values = dict(zip(base_columns, metadata, strict=True))
        return RunEntry(
            id=str(values["id"]),
            model_id=str(values["model_id"]),
            created_at=values.get("created_at"),
            run=None,
            error=f"Invalid run data: {exc}",
        )


def _open_validated(path: Path) -> tuple[sqlite3.Connection, set[str], set[str], set[str]]:
    conn = _connect(path)
    try:
        tables = _tables(conn)
        run_columns, result_columns = _validate_schema(conn)
        return conn, tables, run_columns, result_columns
    except (sqlite3.Error, DatabaseReadError) as exc:
        conn.close()
        if isinstance(exc, DatabaseReadError):
            raise
        raise DatabaseReadError(f"Could not read database schema: {exc}") from exc


def read_run(path: Path, run_id: str) -> RunEntry | None:
    """Read one saved run, preserving malformed payload errors in its entry."""
    conn, tables, run_columns, result_columns = _open_validated(Path(path))
    try:
        return _entry(conn, run_id, run_columns, result_columns, tables)
    except sqlite3.Error as exc:
        raise DatabaseReadError(f"Could not read run: {exc}") from exc
    finally:
        conn.close()


def read_page(
    path: Path,
    *,
    page: int = 1,
    model: str = "",
    suite: str = "",
    seed: int | None = None,
) -> RunPage:
    """Read one 25-run page after applying metadata filters."""
    page = max(1, page)
    conn, tables, run_columns, result_columns = _open_validated(Path(path))
    try:
        selected = [
            column
            for column in ("id", "model_id", "suite_versions", "seed", "created_at")
            if column in run_columns
        ]
        order = "created_at DESC, id DESC" if "created_at" in run_columns else "id DESC"
        rows = conn.execute(
            f"SELECT {', '.join(selected)} FROM runs ORDER BY {order}"
        ).fetchall()
        names = selected
        matching: list[str] = []
        for row in rows:
            metadata = dict(zip(names, row, strict=True))
            if model and model.casefold() not in str(metadata["model_id"]).casefold():
                continue
            if seed is not None and metadata.get("seed") != seed:
                continue
            if suite:
                try:
                    versions = json.loads(metadata.get("suite_versions") or "{}")
                except (TypeError, json.JSONDecodeError):
                    versions = None
                if not isinstance(versions, Mapping):
                    # Keep records with unusable suite metadata visible as invalid
                    # entries; silently excluding them would hide corrupt history.
                    matching.append(str(metadata["id"]))
                    continue
                if suite not in versions:
                    continue
            matching.append(str(metadata["id"]))
        total = len(matching)
        start = (page - 1) * 25
        entries = [
            entry
            for run_id in matching[start : start + 25]
            if (entry := _entry(conn, run_id, run_columns, result_columns, tables)) is not None
        ]
        return RunPage(entries=entries, page=page, total=total)
    except sqlite3.Error as exc:
        raise DatabaseReadError(f"Could not read runs: {exc}") from exc
    finally:
        conn.close()
