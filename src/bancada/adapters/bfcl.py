from __future__ import annotations

from pathlib import Path
from typing import Any

from bancada.adapters.jsonl import read_jsonl
from bancada.models import Case, Gabarito, MachineCheck, Stance


def adapt_bfcl(path: Path | str) -> list[Case]:
    cases: list[Case] = []
    for row in read_jsonl(path):
        record_id = str(row.get("id") or "")
        functions = row.get("function") or []
        if isinstance(functions, dict):
            functions = [functions]
        tools = [_as_openai_tool(fn) for fn in functions if isinstance(fn, dict)]
        expected = row.get("expected_tool", _infer_expected(record_id, row))
        if expected == "":
            expected = None
        stance = Stance.ACCEPT_TRUE_CONTROL if expected else Stance.ACCEPT_TRUE_CONTROL
        notes = "Call the listed tool." if expected else "Do not call a tool."
        cases.append(
            Case(
                id=f"imported.bfcl.{record_id}",
                suite="tools",
                source="imported.bfcl",
                prompt=_question_text(row.get("question") or row.get("prompt") or ""),
                tools=tools or None,
                gabarito=Gabarito(stance=stance, notes=notes),
                machine_checks=[MachineCheck(type="tool_name", expected=expected)],
            )
        )
    return cases


def _infer_expected(record_id: str, row: dict[str, Any]) -> str | None:
    if "irr" in record_id.lower() or row.get("irrelevance"):
        return None
    functions = row.get("function") or []
    if isinstance(functions, dict):
        return functions.get("name")
    if functions and isinstance(functions[0], dict):
        return functions[0].get("name")
    return None


def _question_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        for turn in raw:
            if isinstance(turn, list):
                for msg in turn:
                    if isinstance(msg, dict) and msg.get("content"):
                        return str(msg["content"])
            elif isinstance(turn, dict) and turn.get("content"):
                return str(turn["content"])
    return str(raw or "")


def _as_openai_tool(fn: dict[str, Any]) -> dict[str, Any]:
    if fn.get("type") == "function" and "function" in fn:
        return fn
    return {
        "type": "function",
        "function": {
            "name": fn.get("name"),
            "description": fn.get("description") or "",
            "parameters": _openai_params(fn.get("parameters")),
        },
    }


def _openai_params(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        return {"type": "object", "properties": {}}
    out = dict(params)
    if out.get("type") == "dict":
        out["type"] = "object"
    out.setdefault("type", "object")
    out.setdefault("properties", {})
    return out
