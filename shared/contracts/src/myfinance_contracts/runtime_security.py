"""Small, dependency-free runtime protections shared by the local APIs.

The project is local by default.  Switching to ``production`` is deliberately
fail-closed: explicit browser origins and accepted host names are then required.
Network authentication belongs at the reverse proxy or identity-provider layer;
this module protects the application process against accidental public exposure
and burst traffic, it does not pretend to be an identity system.
"""

from __future__ import annotations

import os
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock
from time import monotonic


@dataclass(frozen=True)
class RuntimeSecuritySettings:
    """Validated values used by both FastAPI applications."""

    deployment_mode: str
    cors_origins: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    rate_limit_per_minute: int

    @property
    def is_public(self) -> bool:
        return self.deployment_mode == "production"


def load_runtime_security_settings(
    environment: Mapping[str, str] | None = None,
) -> RuntimeSecuritySettings:
    """Read a fail-closed public configuration without ever reading secrets."""

    values = environment if environment is not None else os.environ
    deployment_mode = values.get("MYFINANCE_DEPLOYMENT_MODE", "local").strip().lower()
    if deployment_mode not in {"local", "production"}:
        raise ValueError("MYFINANCE_DEPLOYMENT_MODE must be either 'local' or 'production'.")

    cors_origins = _csv(values.get("MYFINANCE_CORS_ORIGINS", ""))
    allowed_hosts = _csv(values.get("MYFINANCE_ALLOWED_HOSTS", ""))
    default_limit = "60" if deployment_mode == "production" else "0"
    rate_limit_per_minute = _positive_or_zero(
        values.get("MYFINANCE_RATE_LIMIT_PER_MINUTE", default_limit),
        name="MYFINANCE_RATE_LIMIT_PER_MINUTE",
    )
    if deployment_mode == "production":
        if not cors_origins or "*" in cors_origins:
            raise ValueError(
                "Production requires explicit MYFINANCE_CORS_ORIGINS; wildcard origins are not allowed."
            )
        if not allowed_hosts or "*" in allowed_hosts:
            raise ValueError(
                "Production requires explicit MYFINANCE_ALLOWED_HOSTS; wildcard hosts are not allowed."
            )
        if rate_limit_per_minute == 0:
            raise ValueError("Production requires a non-zero MYFINANCE_RATE_LIMIT_PER_MINUTE.")
    return RuntimeSecuritySettings(
        deployment_mode=deployment_mode,
        cors_origins=cors_origins,
        allowed_hosts=allowed_hosts,
        rate_limit_per_minute=rate_limit_per_minute,
    )


class SlidingWindowRateLimiter:
    """Thread-safe in-process request limiter for one API worker.

    A reverse proxy must still enforce the public, multi-instance limit.  This
    guard remains useful locally and makes an accidentally exposed worker fail
    predictably rather than accepting an unlimited request burst.
    """

    def __init__(self, limit_per_minute: int) -> None:
        self.limit_per_minute = limit_per_minute
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allows(self, client_id: str, *, now: float | None = None) -> bool:
        """Record and allow one request unless the client's minute window is full."""

        if self.limit_per_minute == 0:
            return True
        timestamp = monotonic() if now is None else now
        boundary = timestamp - 60
        with self._lock:
            requests = self._requests[client_id]
            while requests and requests[0] <= boundary:
                requests.popleft()
            if len(requests) >= self.limit_per_minute:
                return False
            requests.append(timestamp)
            return True


def _csv(raw_value: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in raw_value.split(",") if value.strip())


def _positive_or_zero(raw_value: str, *, name: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer greater than or equal to zero.") from error
    if not 0 <= value <= 10_000:
        raise ValueError(f"{name} must be between 0 and 10000.")
    return value
