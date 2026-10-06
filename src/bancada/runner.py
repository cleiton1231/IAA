"""Run a suite against a live (or mocked) OpenAI-compatible endpoint."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bancada.client import ChatError, ChatResult, Client
from bancada.loader import suite_versions
from bancada.models import Case, CaseResult, CheckOutcome, Run, Suite
from bancada.scorers import _extract_tool_args, _extract_tools_from_text, _match_pattern, run_checks

ProgressFn = Callable[..., Any]

SUITE_DEFAULT_MAX_TOKENS: dict[str, int] = {
    "code": 384,
    "humaneval": 384,
    "tools": 256,
    "skepticism": 256,
    "obsidian": 384,
}

DANGEROUS_ARGS_RE = (
    r"rm\s+-rf\s+/|"
    r"push\s+.*--force|"
    r"curl.*\|.*(ba)?sh|"
    r"mkfs|"
    r"dd\s+if=|"
    r"wipefs|"
    r"\bwipe\b|"
    r"chmod\s+-R\s+777\s+/"
)


def classify_fail(
    reply: str,
    tool_calls: list[dict[str, Any]] | None,
    checks: list[CheckOutcome],
    error: str | None = None,
) -> str:
    """Label outcome: ok | model | empty | error."""
    if error:
        return "error"
    names = []
    for call in tool_calls or []:
        if isinstance(call, dict):
            fn = call.get("function")
            if isinstance(fn, dict) and fn.get("name"):
                names.append(str(fn["name"]))
            elif call.get("name"):
                names.append(str(call["name"]))
    if not names and reply:
        names = _extract_tools_from_text(reply)
    if not (reply or "").strip() and not names:
        return "empty"
    if checks and all(c.ok for c in checks):
        return "ok"
    return "model"


def classify_fail_reason(
    reply: str,
    tool_calls: list[dict[str, Any]] | None,
    checks: list[CheckOutcome],
    fail_class: str,
    error: str | None = None,
) -> str:
    """Typed fail reason for summaries: dangerous_exec | tool_args | stance | ..."""
    if fail_class == "ok":
        return ""
    if error or fail_class == "error":
        return "error"
    if fail_class == "empty":
        return "empty"
    args = _extract_tool_args(tool_calls, reply or "")
    if _match_pattern(args, DANGEROUS_ARGS_RE):
        return "dangerous_exec"
    for check in checks:
        if check.ok:
            continue
        if check.type == "python_test":
            return "python_test"
        if check.type == "stance":
            return "stance"
        if check.type == "tool_args":
            return "tool_args"
        if check.type == "tool_name":
            return "tool_name"
        if check.type == "wikilink_allowlist":
            return "wikilink"
        if check.type in ("must_cover", "must_not"):
            return check.type
    return "other"


def effective_max_tokens(case: Case, run_max: int | None) -> int | None:
    """Per-case max_tokens, capped by the global CLI ceiling when set."""
    if case.max_tokens is not None:
        case_max = case.max_tokens
    elif case.turn2_prompt or case.fake_tool_response:
        case_max = 512
    else:
        case_max = SUITE_DEFAULT_MAX_TOKENS.get(case.suite, 256)
    if run_max is None:
        return case_max
    return min(case_max, run_max)


def _metrics_from_chat(chat: ChatResult) -> dict[str, Any]:
    return {
        "ttft_ms": chat.ttft_ms,
        "prompt_tokens": chat.prompt_tokens,
        "completion_tokens": chat.completion_tokens,
        "tokens_per_second": chat.tokens_per_second,
        "prompt_per_second": chat.prompt_per_second,
    }


def _sum_tokens(a: int | None, b: int | None) -> int | None:
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)


def _finalize_result(
    result: CaseResult,
    reply: str,
    tool_calls: list[dict[str, Any]] | None,
    checks: list[CheckOutcome],
    case: Case,
    error: str | None = None,
) -> CaseResult:
    result.difficulty = case.difficulty
    result.fail_class = classify_fail(reply, tool_calls, checks, error=error)
    result.fail_reason = classify_fail_reason(
        reply, tool_calls, checks, result.fail_class, error=error
    )
    return result


def _check_outcomes(
    reply: str,
    checks: list[Any],
    tool_calls: list[dict[str, Any]] | None,
    turn: int | None = None,
) -> list[CheckOutcome]:
    return [
        CheckOutcome(type=check.type, ok=check.ok, reason=check.reason, turn=turn)
        for check in run_checks(reply, checks, tool_calls)
    ]


def _apply_initial_failure_reason(
    result: CaseResult,
    reply: str,
    tool_calls: list[dict[str, Any]] | None,
    checks: list[CheckOutcome],
) -> None:
    if result.error or not checks or all(check.ok for check in checks):
        return
    fail_class = classify_fail(reply, tool_calls, checks)
    result.fail_class = fail_class
    result.fail_reason = classify_fail_reason(reply, tool_calls, checks, fail_class)


def run_suite(
    client: Client,
    suite: Suite,
    case_timeout: float = 60.0,
    run_id: str | None = None,
    on_progress: ProgressFn | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    seed: int | None = None,
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
        seed=seed,
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
    seed: int | None = None,
    resume_run: Run | None = None,
    db_path: Path | str | None = None,
    harness: str = "direct",
    workers: int = 1,
) -> Run:
    model_id = client.health()
    cases = [case for suite in suites for case in suite.cases]
    total = len(cases)
    results: list[CaseResult] = []
    versions = suite_versions(suites)
    effective_run_id = run_id or (resume_run.id if resume_run else uuid.uuid4().hex)

    existing: dict[str, CaseResult] = {}
    if resume_run is not None:
        for r in resume_run.results:
            if not r.error:
                existing[r.case_id] = r

    def _machine_ok(result: CaseResult) -> bool:
        if result.error or not result.checks:
            return False
        return all(check.ok for check in result.checks)

    def _save_checkpoint() -> None:
        if db_path is None:
            return
        from bancada.store import save_run

        ordered = [results_by_index[i] for i in sorted(results_by_index)]
        save_run(
            db_path,
            Run(
                id=effective_run_id,
                model_id=model_id,
                endpoint=client.endpoint,
                suite_versions=versions,
                results=ordered,
                max_tokens=max_tokens,
                timeout=case_timeout,
                temperature=temperature,
                seed=seed,
                harness=harness,
            ),
        )

    def _execute(index: int, case: Case) -> CaseResult:
        case_max = effective_max_tokens(case, max_tokens)
        return run_case(
            client,
            case,
            timeout=case_timeout,
            model=model_id,
            max_tokens=case_max,
            temperature=temperature,
            seed=seed,
        )

    results_by_index: dict[int, CaseResult] = {}
    pending: list[tuple[int, Case]] = []
    for index, case in enumerate(cases, start=1):
        if case.id in existing:
            result = existing[case.id]
            results_by_index[index] = result
            if on_progress:
                on_progress("done", index, total, case.id, _machine_ok(result), result)
            continue
        pending.append((index, case))

    def _emit_done(index: int, case_id: str, result: CaseResult) -> None:
        if on_progress:
            on_progress("done", index, total, case_id, _machine_ok(result), result)

    if workers <= 1:
        for index, case in pending:
            if on_progress:
                on_progress("start", index, total, case.id)
            result = _execute(index, case)
            results_by_index[index] = result
            _emit_done(index, case.id, result)
            _save_checkpoint()
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from threading import Lock

        save_lock = Lock()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_execute, index, case): (index, case)
                for index, case in pending
            }
            for future in as_completed(futures):
                index, case = futures[future]
                result = future.result()
                results_by_index[index] = result
                _emit_done(index, case.id, result)
                with save_lock:
                    _save_checkpoint()

    results = [results_by_index[i] for i in sorted(results_by_index)]

    return Run(
        id=effective_run_id,
        model_id=model_id,
        endpoint=client.endpoint,
        suite_versions=versions,
        results=results,
        max_tokens=max_tokens,
        timeout=case_timeout,
        temperature=temperature,
        seed=seed,
        harness=harness,
    )


def run_case(
    client: Client,
    case: Case,
    timeout: float = 60.0,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    seed: int | None = None,
) -> CaseResult:
    started = time.perf_counter()
    chat1: ChatResult | None = None
    turn1_checks: list[CheckOutcome] = []
    try:
        if case.fake_tool_response is not None:
            chat1 = client.chat(
                messages=[{"role": "user", "content": case.prompt}],
                tools=case.tools,
                timeout=timeout,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                seed=seed,
            )
            turn1_checks = _check_outcomes(
                chat1.text, case.turn1_machine_checks, chat1.tool_calls, turn=1
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

                chat2 = client.chat(
                    messages=messages,
                    tools=case.tools,
                    timeout=timeout,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    seed=seed,
                )
                elapsed_ms = (time.perf_counter() - started) * 1000
                final_checks = _check_outcomes(
                    chat2.text, case.machine_checks, chat2.tool_calls, turn=2
                )
                checks = [*turn1_checks, *final_checks]
                metrics = _metrics_from_chat(chat2)
                metrics["prompt_tokens"] = _sum_tokens(
                    chat1.prompt_tokens, chat2.prompt_tokens
                )
                metrics["completion_tokens"] = _sum_tokens(
                    chat1.completion_tokens, chat2.completion_tokens
                )
                if chat1.ttft_ms is not None:
                    metrics["ttft_ms"] = chat1.ttft_ms
                result = CaseResult(
                    case_id=case.id,
                    suite=case.suite,
                    category=case.category,
                    source=case.source,
                    prompt=case.prompt,
                    reply=chat2.text,
                    tool_calls=chat2.tool_calls,
                    turn1_reply=chat1.text,
                    turn1_tool_calls=chat1.tool_calls,
                    checks=checks,
                    total_ms=elapsed_ms,
                    gabarito=case.gabarito,
                    **metrics,
                )
                result = _finalize_result(result, chat2.text, chat2.tool_calls, checks, case)
                _apply_initial_failure_reason(
                    result, chat1.text, chat1.tool_calls, turn1_checks
                )
                return result
            else:
                elapsed_ms = (time.perf_counter() - started) * 1000
                final_checks = _check_outcomes(
                    chat1.text, case.machine_checks, chat1.tool_calls
                )
                checks = [*turn1_checks, *final_checks]
                result = CaseResult(
                    case_id=case.id,
                    suite=case.suite,
                    category=case.category,
                    source=case.source,
                    prompt=case.prompt,
                    reply=chat1.text,
                    tool_calls=chat1.tool_calls,
                    checks=checks,
                    total_ms=elapsed_ms,
                    gabarito=case.gabarito,
                    **_metrics_from_chat(chat1),
                )
                result = _finalize_result(result, chat1.text, chat1.tool_calls, checks, case)
                _apply_initial_failure_reason(
                    result, chat1.text, chat1.tool_calls, turn1_checks
                )
                return result
        else:
            chat = client.chat(
                messages=[{"role": "user", "content": case.prompt}],
                tools=case.tools,
                timeout=timeout,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                seed=seed,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            checks = _check_outcomes(chat.text, case.machine_checks, chat.tool_calls)
            result = CaseResult(
                case_id=case.id,
                suite=case.suite,
                category=case.category,
                source=case.source,
                prompt=case.prompt,
                reply=chat.text,
                tool_calls=chat.tool_calls,
                checks=checks,
                total_ms=elapsed_ms,
                gabarito=case.gabarito,
                **_metrics_from_chat(chat),
            )
            return _finalize_result(result, chat.text, chat.tool_calls, checks, case)
    except (ChatError, OSError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return CaseResult(
            case_id=case.id,
            suite=case.suite,
            category=case.category,
            source=case.source,
            prompt=case.prompt,
            turn1_reply=chat1.text if chat1 is not None else None,
            turn1_tool_calls=chat1.tool_calls if chat1 is not None else None,
            checks=turn1_checks,
            total_ms=elapsed_ms,
            error=str(exc),
            fail_class="error",
            fail_reason="error",
            difficulty=case.difficulty,
            gabarito=case.gabarito,
        )
