"""OpenAI-compatible HTTP client for a local llama-server endpoint."""

from __future__ import annotations

import httpx


class ClientError(Exception):
    """Base error for the Bancada HTTP client."""


class HealthError(ClientError):
    """Endpoint is down, not OpenAI-compatible, or lists no models."""


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
