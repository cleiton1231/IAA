"""Deterministic structural checks on a model reply."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

from bancada.models import MachineCheck

FENCE_RE = re.compile(r"```(?:python)?\n(.*?)```", re.DOTALL | re.IGNORECASE)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
PYTHON_TEST_TIMEOUT = 2.0


@dataclass
class CheckResult:
    type: str
    ok: bool
    reason: str = ""


def extract_code(text: str) -> str:
    match = FENCE_RE.search(text or "")
    if match:
        return match.group(1).strip()
    return (text or "").strip()


def run_checks(
    reply: str,
    checks: list[MachineCheck],
    tool_calls: list[dict[str, Any]] | None,
) -> list[CheckResult]:
    return [_run_one(reply, check, tool_calls) for check in checks]


def _run_one(
    reply: str,
    check: MachineCheck,
    tool_calls: list[dict[str, Any]] | None,
) -> CheckResult:
    if check.type == "extract_code":
        code = extract_code(reply)
        ok = bool(code)
        return CheckResult("extract_code", ok, "" if ok else "no code extracted")
    if check.type == "python_test":
        return _python_test(reply, check.source or "")
    if check.type == "wikilink_allowlist":
        return _wikilinks(reply, check.allowed or [])
    if check.type == "tool_name":
        return _tool_name(tool_calls, check.expected)
    if check.type == "not_empty":
        ok = bool((reply or "").strip())
        return CheckResult("not_empty", ok, "" if ok else "empty reply")
    return CheckResult(check.type, False, f"unknown check {check.type}")


def _python_test(reply: str, source: str) -> CheckResult:
    code = extract_code(reply)
    script = f"{code}\n{source}\n"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONSAFEPATH": "1",
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "case.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        try:
            proc = subprocess.run(
                [sys.executable, "-I", path],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                timeout=PYTHON_TEST_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return CheckResult("python_test", False, "timeout")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "failed").strip().splitlines()[-1]
        return CheckResult("python_test", False, err)
    return CheckResult("python_test", True, "")


def _wikilinks(reply: str, allowed: list[str]) -> CheckResult:
    found = WIKILINK_RE.findall(reply or "")
    allow = set(allowed)
    unknown = [name for name in found if name not in allow]
    if unknown:
        return CheckResult("wikilink_allowlist", False, f"unknown wikilinks: {', '.join(unknown)}")
    return CheckResult("wikilink_allowlist", True, "")


def _tool_name(
    tool_calls: list[dict[str, Any]] | None,
    expected: str | None,
) -> CheckResult:
    names = _tool_names(tool_calls)
    if expected is None:
        if names:
            return CheckResult("tool_name", False, f"unexpected tool {names[0]}")
        return CheckResult("tool_name", True, "")
    if expected in names:
        return CheckResult("tool_name", True, "")
    return CheckResult("tool_name", False, f"expected {expected}, got {names or 'none'}")


def _tool_names(tool_calls: list[dict[str, Any]] | None) -> list[str]:
    names: list[str] = []
    for call in tool_calls or []:
        function = call.get("function") if isinstance(call, dict) else None
        if isinstance(function, dict) and function.get("name"):
            names.append(str(function["name"]))
        elif isinstance(call, dict) and call.get("name"):
            names.append(str(call["name"]))
    return names
