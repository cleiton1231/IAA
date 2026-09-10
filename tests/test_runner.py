"""Runner requires health, scores each case, and survives a dead request."""

import json

import httpx
import pytest

from bancada.client import Client, HealthError
from bancada.models import Case, Gabarito, MachineCheck, Stance, Suite
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
