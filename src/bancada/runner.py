"""Run a suite against a live (or mocked) OpenAI-compatible endpoint."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bancada.client import ChatError, Client
from bancada.models import Case, CaseResult, CheckOutcome, Run, Suite
from bancada.scorers import _extract_tools_from_text, run_checks

ProgressFn = Callable[..., Any]


def run_suite(
    client: Client,
    suite: Suite,
    case_timeout: float = 60.0,
    run_id: str | None = None,
    on_progress: ProgressFn | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    resume_run: Run | None = None,
    db_path: Path | str | None = None,
) -> Run:
    return run_many(
        client,
        [suite],
        case_timeout=case_timeout,
        run_id=run_id,
        on_progress=on_progress,
        max_tokens=max_tokens,
        temperature=temperature,
        resume_run=resume_run,
        db_path=db_path,
    )


def run_many(
    client: Client,
    suites: list[Suite],
    case_timeout: float = 60.0,
    run_id: str | None = None,
    on_progress: ProgressFn | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    resume_run: Run | None = None,
    db_path: Path | str | None = None,
) -> Run:
    model_id = client.health()
    cases = [case for suite in suites for case in suite.cases]
    total = len(cases)
    results: list[CaseResult] = []
    versions: dict[str, int] = {suite.name: suite.version for suite in suites}
    effective_run_id = run_id or (resume_run.id if resume_run else uuid.uuid4().hex)

    existing: dict[str, CaseResult] = {}
    if resume_run is not None:
        for r in resume_run.results:
            if not r.error:
                existing[r.case_id] = r

    for index, case in enumerate(cases, start=1):
        if case.id in existing:
            result = existing[case.id]
            results.append(result)
            if on_progress:
                if result.error or not result.checks:
                    machine_ok = False
                else:
                    machine_ok = all(check.ok for check in result.checks)
                on_progress("done", index, total, case.id, machine_ok, result)
            continue

        if on_progress:
            on_progress("start", index, total, case.id)
        result = run_case(
            client,
            case,
            timeout=case_timeout,
            model=model_id,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        results.append(result)
        if on_progress:
            if result.error or not result.checks:
                machine_ok = False
            else:
                machine_ok = all(check.ok for check in result.checks)
            on_progress("done", index, total, case.id, machine_ok, result)

        if db_path:
            from bancada.store import save_run

            current_run = Run(
                id=effective_run_id,
                model_id=model_id,
                endpoint=client.endpoint,
                suite_versions=versions,
                results=results,
                max_tokens=max_tokens,
                timeout=case_timeout,
                temperature=temperature,
            )
            save_run(db_path, current_run)

    return Run(
        id=effective_run_id,
        model_id=model_id,
        endpoint=client.endpoint,
        suite_versions=versions,
        results=results,
        max_tokens=max_tokens,
        timeout=case_timeout,
        temperature=temperature,
    )


def run_case(
    client: Client,
    case: Case,
    timeout: float = 60.0,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> CaseResult:
    started = time.perf_counter()
    try:
        if case.fake_tool_response is not None:
            # Turn 1
            chat1 = client.chat(
                messages=[{"role": "user", "content": case.prompt}],
                tools=case.tools,
                timeout=timeout,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            tools_in_text = _extract_tools_from_text(chat1.text)
            has_tool = bool(chat1.tool_calls) or bool(tools_in_text)

            if has_tool:
                messages: list[dict[str, Any]] = [
                    {"role": "user", "content": case.prompt},
                ]
                if chat1.tool_calls:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": chat1.text or None,
                            "tool_calls": chat1.tool_calls,
                        }
                    )
                    for tc in chat1.tool_calls:
                        func = tc.get("function", {}) if isinstance(tc, dict) else {}
                        name = func.get("name") or tc.get("name") or "exec"
                        call_id = tc.get("id") or "call_1"
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": name,
                                "content": case.fake_tool_response,
                            }
                        )
                else:
                    messages.append({"role": "assistant", "content": chat1.text})
                    messages.append(
                        {
                            "role": "user",
                            "content": f"[Tool output]:\n{case.fake_tool_response}",
                        }
                    )

                if case.turn2_prompt:
                    messages.append({"role": "user", "content": case.turn2_prompt})

                # Turn 2
                chat2 = client.chat(
                    messages=messages,
                    tools=case.tools,
                    timeout=timeout,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                elapsed_ms = (time.perf_counter() - started) * 1000
                checks = run_checks(chat2.text, case.machine_checks, chat2.tool_calls)
                return CaseResult(
                    case_id=case.id,
                    suite=case.suite,
                    category=case.category,
                    source=case.source,
                    prompt=case.prompt,
                    reply=chat2.text,
                    tool_calls=chat2.tool_calls,
                    turn1_reply=chat1.text,
                    turn1_tool_calls=chat1.tool_calls,
                    checks=[CheckOutcome(type=c.type, ok=c.ok, reason=c.reason) for c in checks],
                    total_ms=elapsed_ms,
                    gabarito=case.gabarito,
                )
            else:
                elapsed_ms = (time.perf_counter() - started) * 1000
                checks = run_checks(chat1.text, case.machine_checks, chat1.tool_calls)
                return CaseResult(
                    case_id=case.id,
                    suite=case.suite,
                    category=case.category,
                    source=case.source,
                    prompt=case.prompt,
                    reply=chat1.text,
                    tool_calls=chat1.tool_calls,
                    checks=[CheckOutcome(type=c.type, ok=c.ok, reason=c.reason) for c in checks],
                    total_ms=elapsed_ms,
                    gabarito=case.gabarito,
                )
        else:
            chat = client.chat(
                messages=[{"role": "user", "content": case.prompt}],
                tools=case.tools,
                timeout=timeout,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            checks = run_checks(chat.text, case.machine_checks, chat.tool_calls)
            return CaseResult(
                case_id=case.id,
                suite=case.suite,
                category=case.category,
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
            category=case.category,
            source=case.source,
            prompt=case.prompt,
            total_ms=elapsed_ms,
            error=str(exc),
            gabarito=case.gabarito,
        )
