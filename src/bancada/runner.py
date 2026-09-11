"""Run a suite against a live (or mocked) OpenAI-compatible endpoint."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from bancada.client import ChatError, Client
from bancada.models import Case, CaseResult, CheckOutcome, Run, Suite
from bancada.scorers import run_checks

ProgressFn = Callable[..., Any]


def run_suite(
    client: Client,
    suite: Suite,
    case_timeout: float = 60.0,
    run_id: str | None = None,
    on_progress: ProgressFn | None = None,
    max_tokens: int | None = None,
) -> Run:
    return run_many(
        client,
        [suite],
        case_timeout=case_timeout,
        run_id=run_id,
        on_progress=on_progress,
        max_tokens=max_tokens,
    )


def run_many(
    client: Client,
    suites: list[Suite],
    case_timeout: float = 60.0,
    run_id: str | None = None,
    on_progress: ProgressFn | None = None,
    max_tokens: int | None = None,
) -> Run:
    model_id = client.health()
    cases = [case for suite in suites for case in suite.cases]
    total = len(cases)
    results: list[CaseResult] = []
    versions: dict[str, int] = {suite.name: suite.version for suite in suites}
    for index, case in enumerate(cases, start=1):
        if on_progress:
            on_progress("start", index, total, case.id)
        result = run_case(
            client,
            case,
            timeout=case_timeout,
            model=model_id,
            max_tokens=max_tokens,
        )
        results.append(result)
        if on_progress:
            if result.error:
                machine_ok = False
            elif not result.checks:
                machine_ok = True
            else:
                machine_ok = all(check.ok for check in result.checks)
            on_progress("done", index, total, case.id, machine_ok, result)
    return Run(
        id=run_id or uuid.uuid4().hex,
        model_id=model_id,
        endpoint=client.endpoint,
        suite_versions=versions,
        results=results,
    )


def run_case(
    client: Client,
    case: Case,
    timeout: float = 60.0,
    model: str | None = None,
    max_tokens: int | None = None,
) -> CaseResult:
    started = time.perf_counter()
    try:
        chat = client.chat(
            messages=[{"role": "user", "content": case.prompt}],
            tools=case.tools,
            timeout=timeout,
            model=model,
            max_tokens=max_tokens,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        checks = run_checks(chat.text, case.machine_checks, chat.tool_calls)
        return CaseResult(
            case_id=case.id,
            suite=case.suite,
            source=case.source,
            prompt=case.prompt,
            reply=chat.text,
            tool_calls=chat.tool_calls,
            checks=[CheckOutcome(type=c.type, ok=c.ok, reason=c.reason) for c in checks],
            total_ms=elapsed_ms,
            gabarito=case.gabarito,
        )
    except (ChatError, OSError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return CaseResult(
            case_id=case.id,
            suite=case.suite,
            source=case.source,
            prompt=case.prompt,
            total_ms=elapsed_ms,
            error=str(exc),
            gabarito=case.gabarito,
        )
