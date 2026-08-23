"""HTTP executor for the real conversation API."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx

from myfinance_autotest.models import ActionKind, Channel, PlannedAction, ToolExecutionResult


class ApiExecutor:
    """Execute a bounded conversation action and retain raw transport evidence."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 50,
        max_retries: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_attempts = max(1, max_retries + 1)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def execute(self, action: PlannedAction) -> ToolExecutionResult:
        if action.channel is not Channel.API:
            raise ValueError("ApiExecutor accepts only API actions.")
        if action.kind is not ActionKind.SEND_MESSAGE or not action.question:
            raise ValueError("The API prototype supports only SEND_MESSAGE actions with a question.")

        started_at = datetime.now(UTC)
        started = time.perf_counter()
        last_error: httpx.HTTPError | None = None
        for _attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.post(
                    f"{self.base_url}/api/conversation/answer",
                    json={"message": action.question, "context": action.parameters.get("context", {})},
                )
                latency = round((time.perf_counter() - started) * 1_000)
                try:
                    body: dict[str, Any] | None = response.json()
                    if not isinstance(body, dict):
                        body = {"raw_json": body}
                except ValueError:
                    body = None
                errors = [] if response.status_code < 400 else [f"HTTP {response.status_code}"]
                return ToolExecutionResult(
                    action_id=action.action_id,
                    channel=Channel.API,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    latency_ms=latency,
                    http_status=response.status_code,
                    response=body,
                    errors=errors,
                )
            except httpx.HTTPError as error:
                last_error = error
        assert last_error is not None
        return ToolExecutionResult(
            action_id=action.action_id,
            channel=Channel.API,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            latency_ms=round((time.perf_counter() - started) * 1_000),
            errors=[f"HTTP transport error after {self._max_attempts} attempt(s): {type(last_error).__name__}"],
        )
