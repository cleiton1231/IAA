"""Health check talks to a real OpenAI-compatible /v1/models JSON body."""

import httpx
import pytest

from bancada.client import Client, HealthError


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/models") and request.method == "GET":
        return httpx.Response(
            200,
            json={"data": [{"id": "Qwen3.5-9B", "object": "model"}]},
        )
    return httpx.Response(404, json={"error": "not found"})


def test_health_returns_first_model_id() -> None:
    transport = httpx.MockTransport(_handler)
    client = Client("http://127.0.0.1:8080/v1", transport=transport)
    assert client.health() == "Qwen3.5-9B"


def test_health_raises_when_http_is_not_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "busy"})

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    with pytest.raises(HealthError, match="503"):
        client.health()


def test_health_raises_when_data_list_is_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    with pytest.raises(HealthError, match="no model"):
        client.health()


def test_chat_sends_model_and_max_tokens() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "toy"}]})
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    result = client.chat(
        [{"role": "user", "content": "oi"}],
        model="toy",
        max_tokens=256,
    )
    assert result.text == "ok"
    assert seen["model"] == "toy"
    assert seen["max_tokens"] == 256


def test_chat_sends_temperature_and_seed() -> None:
    import json

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "toy"}]})
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    client.chat(
        [{"role": "user", "content": "oi"}],
        temperature=0.0,
        seed=42,
    )
    assert seen["temperature"] == 0.0
    assert seen["seed"] == 42


def test_chat_parses_llama_timings_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "toy"}]})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 34},
                "timings": {
                    "prompt_ms": 45.5,
                    "predicted_per_second": 28.3,
                    "prompt_per_second": 120.0,
                },
            },
        )

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    result = client.chat([{"role": "user", "content": "oi"}])
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 34
    assert result.ttft_ms == 45.5
    assert result.tokens_per_second == 28.3
    assert result.prompt_per_second == 120.0


def test_health_raises_on_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    with pytest.raises(HealthError, match="connect"):
        client.health()


def test_client_sends_api_key_and_model_and_extra_body() -> None:
    import json as _json

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "x"}]})
        captured["auth"] = request.headers.get("authorization")
        body = _json.loads(request.content)
        captured["model"] = body.get("model")
        captured["reasoning"] = body.get("reasoning")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7},
            },
        )

    from bancada.client import Client

    client = Client(
        "https://openrouter.ai/api/v1",
        api_key="sk-or-test",
        model="prism-ml/ternary-bonsai-2-27b",
        extra_body={"reasoning": {"enabled": False}},
        transport=httpx.MockTransport(handler),
    )
    assert client.health() == "prism-ml/ternary-bonsai-2-27b"
    result = client.chat(messages=[{"role": "user", "content": "oi"}])
    assert result.text == "ok"
    assert captured["auth"] == "Bearer sk-or-test"
    assert captured["model"] == "prism-ml/ternary-bonsai-2-27b"
    assert captured["reasoning"] == {"enabled": False}


def test_client_retries_on_429_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "m"}]})
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, json={"error": {"message": "rate"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    from bancada.client import Client

    client = Client(
        "https://api.test/v1",
        transport=httpx.MockTransport(handler),
        retry_backoff=0.01,
    )
    result = client.chat(messages=[{"role": "user", "content": "oi"}])
    assert result.text == "ok"
    assert calls["n"] == 3
