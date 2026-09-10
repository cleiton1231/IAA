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


def test_health_raises_on_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(handler))
    with pytest.raises(HealthError, match="connect"):
        client.health()
