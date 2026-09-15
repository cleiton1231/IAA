"""OpenAI-compatible HTTP client for a local llama-server endpoint."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


class ClientError(Exception):
    """Base error for the Bancada HTTP client."""


class HealthError(ClientError):
    """Endpoint is down, not OpenAI-compatible, or lists no models."""


class ChatError(ClientError):
    """Chat completion failed (HTTP, timeout, or malformed body)."""


@dataclass
class ChatResult:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class Client:
    def __init__(
        self,
        endpoint: str,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def health(self) -> str:
        url = f"{self.endpoint}/models"
        try:
            response = self._http.get(url)
        except httpx.ConnectError as exc:
            raise HealthError(f"connect failed: {exc}") from exc
        except httpx.HTTPError as exc:
            raise HealthError(f"health request failed: {exc}") from exc

        if response.status_code != 200:
            raise HealthError(f"health HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise HealthError("health response is not JSON") from exc

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            raise HealthError("no model in /v1/models")

        first = data[0]
        model_id = first.get("id") if isinstance(first, dict) else None
        if not model_id:
            raise HealthError("no model id in /v1/models")
        return str(model_id)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        url = f"{self.endpoint}/chat/completions"
        body: dict[str, Any] = {"messages": messages}
        if tools:
            body["tools"] = tools
        if model:
            body["model"] = model
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        request_timeout = timeout if timeout is not None else self.timeout
        try:
            response = self._http.post(url, json=body, timeout=request_timeout)
        except httpx.TimeoutException as exc:
            raise ChatError(f"timeout: {exc}") from exc
        except httpx.ConnectError as exc:
            raise ChatError(f"connect failed: {exc}") from exc
        except httpx.HTTPError as extra:
            raise ChatError(f"chat request failed: {extra}") from extra

        if response.status_code != 200:
            raise ChatError(f"chat HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ChatError("chat response is not JSON") from exc
        if not isinstance(payload, dict):
            raise ChatError("chat response is not an object")

        choices = payload.get("choices") or []
        if not choices:
            raise ChatError("chat response has no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise ChatError("chat response missing message")
        text = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            tool_calls = []
        return ChatResult(text=str(text), tool_calls=tool_calls, raw=payload)
