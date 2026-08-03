"""Bounded Groq client for JSON-only agent decisions.

No model output mutates campaign state directly.  Every response is parsed as
JSON and then validated against the caller's Pydantic model before it is usable.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, Field, ValidationError

from myfinance_autotest.config import REQUIRED_GROQ_ROLES, AutotestSettings
from myfinance_autotest.state import CampaignState

ResponseT = TypeVar("ResponseT", bound=BaseModel)
ClientFactory = Callable[..., Any]
Sleep = Callable[[float], None]
Clock = Callable[[], float]


class GroqCallResult(BaseModel):
    """Secret-safe metadata for one role call, suitable for a TraceEvent."""

    role: str
    model: str
    attempts: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    status: str
    error: str | None = None

    def trace_data(self) -> dict[str, object]:
        """Return only operational metadata; neither prompt nor key is retained."""
        return self.model_dump(exclude={"error"}) | ({"error": self.error} if self.error else {})


def _default_client_factory(*, api_key: str, timeout: float) -> Any:
    from groq import Groq

    return Groq(api_key=api_key, timeout=timeout)


def _safe_provider_error_detail(error: Exception) -> str:
    """Return useful provider feedback while never persisting a credential."""

    body = getattr(error, "body", None)
    if isinstance(body, dict):
        payload = body.get("error", body)
        detail = payload.get("message") or payload.get("code") if isinstance(payload, dict) else str(payload)
    else:
        detail = getattr(error, "message", None) or str(error)
    status_code = getattr(error, "status_code", None)
    text = " ".join(str(detail or "").split())[:500]
    text = re.sub(r"gsk_[A-Za-z0-9_-]+", "[secret redacted]", text)
    text = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [secret redacted]", text)
    prefix = f"HTTP {status_code}" if status_code is not None else ""
    return ": ".join(part for part in (prefix, text) if part)


def _json_object_content(content: str) -> str:
    """Accept one JSON object, optionally wrapped in a Markdown code fence."""

    candidate = content.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[1] if "\n" in candidate else ""
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[:-3]
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Groq response does not contain a JSON object.")
    return candidate[start:end + 1]


class GroqClient:
    """Reusable sync client with bounded retries and Pydantic output validation."""

    def __init__(
        self,
        settings: AutotestSettings,
        *,
        client_factory: ClientFactory = _default_client_factory,
        sleep: Sleep = time.sleep,
        clock: Clock = time.perf_counter,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory
        self._sleep = sleep
        self._clock = clock
        self._client: Any | None = None

    def _client_instance(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(
                api_key=self.settings.require_groq_api_key(),
                timeout=float(self.settings.groq.timeout_seconds),
            )
        return self._client

    def complete_json(
        self,
        *,
        role: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseT],
        campaign: CampaignState,
        max_completion_tokens: int = 800,
    ) -> tuple[ResponseT | None, GroqCallResult]:
        """Request one JSON object, validate it, retrying only within budget."""
        if role not in REQUIRED_GROQ_ROLES:
            raise ValueError(f"Unknown Groq agent role: {role}")
        if max_completion_tokens < 1:
            raise ValueError("max_completion_tokens must be positive")

        model = self.settings.resolved_models[role]
        started = self._clock()
        last_error: str | None = None
        for attempt in range(1, self.settings.groq.max_retries + 2):
            try:
                campaign.register_llm_call()
            except RuntimeError as error:
                last_error = str(error)
                break
            try:
                request = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0,
                    "max_completion_tokens": max_completion_tokens,
                    # Provider-enforced JSON can itself fail while decoding a
                    # model output (HTTP 400). We instead request plain text and
                    # enforce JSON plus the Pydantic schema locally below.
                }
                # GPT-OSS defaults to medium reasoning. These agent calls only
                # need short structured decisions; low effort leaves enough of
                # the completion budget for the actual JSON object. Do not send
                # this unsupported parameter to other model families.
                if model.startswith("openai/gpt-oss-"):
                    request["reasoning_effort"] = "low"
                completion = self._client_instance().chat.completions.create(**request)
                content = completion.choices[0].message.content or ""
                parsed = response_model.model_validate(json.loads(_json_object_content(content)))
                usage = getattr(completion, "usage", None)
                result = GroqCallResult(
                    role=role,
                    model=model,
                    attempts=attempt,
                    duration_ms=round((self._clock() - started) * 1_000),
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    completion_tokens=getattr(usage, "completion_tokens", None),
                    status="success",
                )
                return parsed, result
            except (json.JSONDecodeError, ValidationError, IndexError, AttributeError, TypeError, ValueError) as error:
                last_error = f"Invalid structured Groq response: {type(error).__name__}"
            # This is the external-provider boundary: SDK and network exception
            # types vary by provider version, but must become a safe test result.
            except Exception as error:  # noqa: BLE001
                error_name = type(error).__name__
                detail = _safe_provider_error_detail(error)
                last_error = f"Groq request failed: {error_name}{f' ({detail})' if detail else ''}"
                # Retrying a malformed request, an invalid model, or invalid
                # credentials cannot make it valid.  Stop here so one bad
                # configuration does not consume the whole campaign budget.
                if error_name in {"AuthenticationError", "BadRequestError", "NotFoundError", "PermissionDeniedError", "UnprocessableEntityError"}:
                    break
            if attempt <= self.settings.groq.max_retries:
                self._sleep(0.5 * (2 ** (attempt - 1)))

        return None, GroqCallResult(
            role=role,
            model=model,
            attempts=min(self.settings.groq.max_retries + 1, campaign.llm_call_count),
            duration_ms=round((self._clock() - started) * 1_000),
            status="failed",
            error=last_error or "Groq request did not produce a usable response.",
        )
