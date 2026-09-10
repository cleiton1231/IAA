"""Run a suite against a live (or mocked) OpenAI-compatible endpoint."""

from __future__ import annotations

import time
import uuid

from bancada.client import ChatError, Client
from bancada.models import Case, CaseResult, CheckOutcome, Run, Suite
from bancada.scorers import run_checks


def run_suite(
    client: Client,
    suite: Suite,
    case_timeout: float = 60.0,
    run_id: str | None = None,
) -> Run:
    model_id = client.health()
    results = [run_case(client, case, timeout=case_timeout) for case in suite.cases]
    return Run(
        id=run_id or uuid.uuid4().hex,
        model_id=model_id,
        endpoint=client.endpoint,
        suite_versions={suite.name: suite.version},
        results=results,
    )


def run_case(client: Client, case: Case, timeout: float = 60.0) -> CaseResult:
    started = time.perf_counter()
    try:
        chat = client.chat(
            messages=[{"role": "user", "content": case.prompt}],
            tools=case.tools,
            timeout=timeout,
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
