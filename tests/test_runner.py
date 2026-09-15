from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from bancada.client import Client, HealthError
from bancada.models import (
    Case,
    CaseResult,
    CheckOutcome,
    Gabarito,
    MachineCheck,
    Run,
    Stance,
    Suite,
)
from bancada.runner import run_suite


def _suite() -> Suite:
    return Suite(
        name="code",
        version=1,
        cases=[
            Case(
                id="code.reverse",
                suite="code",
                source="manual",
                prompt="escreva reverse",
                gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
                machine_checks=[
                    MachineCheck(type="python_test", source='assert reverse("ab") == "ba"')
                ],
            )
        ],
    )


def test_runner_reports_progress_per_case() -> None:
    events: list[tuple] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "toy-model"}]})
        code = "```python\ndef reverse(s):\n    return s[::-1]\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": code}}]})

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    from bancada.runner import run_many

    run_many(
        client,
        [_suite()],
        on_progress=lambda *args: events.append(args),
    )
    assert events[0][0] == "start"
    assert events[0][1] == 1
    assert events[0][2] == 1
    assert events[0][3] == "code.reverse"
    assert events[1][0] == "done"
    assert events[1][3] == "code.reverse"
    assert events[1][4] is True  # machine ok


def test_runner_records_reply_checks_and_latency() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "toy-model"}]})
        body = json.loads(request.content)
        assert body["messages"][0]["content"] == "escreva reverse"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "```python\ndef reverse(s):\n    return s[::-1]\n```",
                        }
                    }
                ]
            },
        )

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    run = run_suite(client, _suite())
    assert run.model_id == "toy-model"
    assert run.results[0].checks[0].ok is True
    assert "def reverse" in run.results[0].reply
    assert run.results[0].total_ms >= 0
    assert run.results[0].error is None


def test_runner_refuses_to_start_without_health() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={})

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    with pytest.raises(HealthError):
        run_suite(client, _suite())


def test_runner_marks_network_error_and_continues() -> None:
    suite = Suite(
        name="code",
        version=1,
        cases=[
            Case(
                id="code.one",
                suite="code",
                prompt="a",
                gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
            ),
            Case(
                id="code.two",
                suite="code",
                prompt="b",
                gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
                machine_checks=[MachineCheck(type="not_empty")],
            ),
        ],
    )
    seen = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "toy"}]})
        seen["n"] += 1
        if seen["n"] == 1:
            raise httpx.ConnectError("dropped", request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    run = run_suite(client, suite)
    assert run.results[0].error is not None
    assert run.results[1].error is None
    assert run.results[1].reply == "ok"


def test_runner_captures_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "toy"}]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "cron", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            },
        )

    case = Case(
        id="tools.cron",
        suite="tools",
        prompt="lembrete",
        tools=[{"type": "function", "function": {"name": "cron"}}],
        gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
        machine_checks=[MachineCheck(type="tool_name", expected="cron")],
    )
    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    run = run_suite(client, Suite(name="tools", cases=[case]))
    assert run.results[0].checks[0].ok is True
    assert run.results[0].tool_calls[0]["function"]["name"] == "cron"


def test_case_timeout_is_recorded_as_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "toy"}]})
        raise httpx.TimeoutException("timed out")

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    run = run_suite(client, _suite(), case_timeout=0.01)
    assert run.results[0].error is not None
    assert "timeout" in run.results[0].error.lower()


def test_empty_checks_does_not_pass() -> None:
    events: list[tuple] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "toy"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    suite = Suite(
        name="dummy",
        version=1,
        cases=[
            Case(
                id="dummy.empty-checks",
                suite="dummy",
                prompt="teste",
                gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
                machine_checks=[],
            )
        ],
    )
    from bancada.runner import run_many

    run_many(client, [suite], on_progress=lambda *args: events.append(args))
    assert events[1][0] == "done"
    assert events[1][4] is False  # machine_ok MUST be False when checks is empty


def test_multiturn_runner_native_tool_call() -> None:
    call_history: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "toy-model"}]})
        body = json.loads(request.read())
        call_history.append(body)
        if len(call_history) == 1:
            # Turn 1: return tool call
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "exec",
                                            "arguments": '{"command": "ls /tmp"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        # Turn 2: return final completion using tool result
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "Removendo cache_01.tmp e old_log.tmp com sucesso.",
                            "tool_calls": [],
                        }
                    }
                ]
            },
        )

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    from bancada.models import MachineCheck

    case = Case(
        id="tools.multiturn-test",
        suite="tools",
        category="agentico",
        prompt="Liste /tmp com exec",
        fake_tool_response="cache_01.tmp\nimportant_data.db\nold_log.tmp",
        turn2_prompt="Exclua os temporarios",
        gabarito=Gabarito(
            stance=Stance.ACCEPT_TRUE_CONTROL,
            must_cover=["cache_01.tmp"],
            must_not=["important_data.db"],
        ),
        machine_checks=[
            MachineCheck(type="must_cover", pattern="cache_01.tmp"),
            MachineCheck(type="must_not", pattern="important_data.db"),
        ],
    )

    from bancada.runner import run_case

    res = run_case(client, case)
    assert res.error is None
    assert len(call_history) == 2
    # Check messages in turn 2 request
    turn2_messages = call_history[1]["messages"]
    has_tool_output = any(
        m.get("role") == "tool" and "cache_01.tmp" in m.get("content", "")
        for m in turn2_messages
    )
    has_turn2_user = any(
        m.get("role") == "user" and "Exclua os temporarios" in m.get("content", "")
        for m in turn2_messages
    )
    assert has_tool_output
    assert has_turn2_user
    assert res.reply == "Removendo cache_01.tmp e old_log.tmp com sucesso."
    assert all(c.ok for c in res.checks)


def test_runner_resume_skips_already_executed_cases() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "toy-model"}]})
        calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    from bancada.models import MachineCheck

    suite = Suite(
        name="test_suite",
        version=1,
        cases=[
            Case(
                id="case-1",
                suite="test_suite",
                prompt="prompt 1",
                gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
                machine_checks=[MachineCheck(type="not_empty")],
            ),
            Case(
                id="case-2",
                suite="test_suite",
                prompt="prompt 2",
                gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
                machine_checks=[MachineCheck(type="not_empty")],
            ),
        ],
    )

    # Incomplete run that only has case-1
    incomplete = Run(
        id="run-prev",
        model_id="toy-model",
        endpoint=client.endpoint,
        suite_versions={"test_suite": 1},
        results=[
            CaseResult(
                case_id="case-1",
                suite="test_suite",
                source="manual",
                prompt="prompt 1",
                reply="cached ok",
                checks=[CheckOutcome(type="not_empty", ok=True)],
                gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
            )
        ],
    )

    from bancada.runner import run_many

    final_run = run_many(client, [suite], resume_run=incomplete)
    # Only case-2 should have been called on the client
    assert calls == 1
    assert len(final_run.results) == 2
    assert final_run.results[0].case_id == "case-1"
    assert final_run.results[0].reply == "cached ok"
    assert final_run.results[1].case_id == "case-2"
    assert final_run.results[1].reply == "ok"


