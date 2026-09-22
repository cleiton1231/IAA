"""OpenAI-compatible HTTP client for a local llama-server endpoint."""

from __future__ import annotations

import time
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
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    ttft_ms: float | None = None
    tokens_per_second: float | None = None
    prompt_per_second: float | None = None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_chat_metrics(payload: dict[str, Any]) -> dict[str, float | int | None]:
    """Extract usage + llama-server timings from a chat completion body."""
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    timings = payload.get("timings") if isinstance(payload.get("timings"), dict) else {}
    return {
        "prompt_tokens": _as_int(usage.get("prompt_tokens")),
        "completion_tokens": _as_int(usage.get("completion_tokens")),
        "ttft_ms": _as_float(timings.get("prompt_ms")),
        "tokens_per_second": _as_float(timings.get("predicted_per_second")),
        "prompt_per_second": _as_float(timings.get("prompt_per_second")),
    }


class Client:
    def __init__(
        self,
        endpoint: str,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        api_key: str | None = None,
        model: str | None = None,
        extra_body: dict[str, Any] | None = None,
        retry_backoff: float = 8.0,
        max_attempts: int = 3,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.model = model
        self.extra_body = dict(extra_body or {})
        self.retry_backoff = retry_backoff
        self.max_attempts = max_attempts
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        self._http = httpx.Client(
            timeout=timeout, transport=transport, headers=headers
        )

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
        if self.model:
            return self.model
        return str(model_id)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> ChatResult:
        url = f"{self.endpoint}/chat/completions"
        body: dict[str, Any] = dict(self.extra_body)
        body["messages"] = messages
        if tools:
            body["tools"] = tools
        if model:
            body["model"] = model
        elif self.model:
            body["model"] = self.model
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if seed is not None:
            body["seed"] = seed
        request_timeout = timeout if timeout is not None else self.timeout
        response = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._http.post(url, json=body, timeout=request_timeout)
            except httpx.TimeoutException as exc:
                raise ChatError(f"timeout: {exc}") from exc
            except httpx.ConnectError as exc:
                raise ChatError(f"connect failed: {exc}") from exc
            except httpx.HTTPError as extra:
                raise ChatError(f"chat request failed: {extra}") from extra
            if (
                response.status_code in (429, 500, 502, 503)
                and attempt < self.max_attempts
            ):
                if self.retry_backoff > 0:
                    time.sleep(self.retry_backoff * attempt)
                continue
            break
        assert response is not None

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
        metrics = parse_chat_metrics(payload)
        return ChatResult(
            text=str(text),
            tool_calls=tool_calls,
            raw=payload,
            prompt_tokens=metrics["prompt_tokens"],  # type: ignore[arg-type]
            completion_tokens=metrics["completion_tokens"],  # type: ignore[arg-type]
            ttft_ms=metrics["ttft_ms"],  # type: ignore[arg-type]
            tokens_per_second=metrics["tokens_per_second"],  # type: ignore[arg-type]
            prompt_per_second=metrics["prompt_per_second"],  # type: ignore[arg-type]
        )
