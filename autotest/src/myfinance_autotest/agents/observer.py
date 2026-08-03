"""Normalise raw executor results into read-only observations."""

from __future__ import annotations

from datetime import UTC, datetime

from myfinance_autotest.models import Observation, ToolExecutionResult


def observe_execution(
    observation_id: str, execution: ToolExecutionResult, *, session_id: str | None = None
) -> Observation:
    """Collect what the executor observed without assigning a verdict."""
    response = execution.response or {}
    visible_response = next(
        (
            str(response[field])
            for field in ("answer", "message", "detail")
            if response.get(field) is not None
        ),
        None,
    )
    return Observation(
        observation_id=observation_id,
        channel=execution.channel,
        observed_at=datetime.now(UTC),
        session_id=session_id,
        visible_response=visible_response,
        execution=execution,
        errors=list(execution.errors),
    )
