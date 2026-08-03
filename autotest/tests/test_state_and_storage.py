"""Tests for campaign stopping rules and replayable, secret-safe trace storage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from myfinance_autotest import models
from myfinance_autotest.config import CampaignLimits
from myfinance_autotest.observability.storage import JsonlTraceStore
from myfinance_autotest.state import CampaignState, CampaignStep


def _case() -> models.TestCase:
    objective = models.TestObjective(
        objective_id="OBJ-1",
        category=models.TestCategory.FINANCIAL_FACT,
        description="Vérifier la valeur source.",
        required_properties=["supported_by_source"],
        rationale="Une réponse financière doit être prouvée.",
    )
    return models.TestCase(
        test_id="TEST-1",
        title="PNB BIAT",
        category=models.TestCategory.FINANCIAL_FACT,
        channels=[models.Channel.API],
        input="Quel est le PNB de BIAT en 2025 ?",
        objective=objective,
        expected_properties=["supported_by_source"],
        failure_criteria=["unsupported_value"],
    )


def _step(sequence: int, question: str = "Quel est le PNB de BIAT en 2025 ?") -> CampaignStep:
    case = _case()
    return CampaignStep(
        step_id=f"STEP-{sequence}",
        sequence=sequence,
        objective=case.objective,
        action=models.PlannedAction(
            action_id=f"ACTION-{sequence}",
            objective_id=case.objective.objective_id,
            kind=models.ActionKind.SEND_MESSAGE,
            channel=models.Channel.API,
            question=question,
            rationale="Vérifier la réponse sur le canal API.",
        ),
    )


def test_campaign_stops_after_repeated_actions() -> None:
    limits = CampaignLimits(
        max_agent_steps=8,
        max_llm_calls_per_test=5,
        global_test_timeout_seconds=120,
        max_repeated_actions=2,
        min_evidence_confidence=0.8,
    )
    state = CampaignState.initialise(_case(), limits)
    state.record_step(_step(1))
    state.record_step(_step(2))
    state.record_step(_step(3))

    assert state.evaluate_stop_condition() == "repeated_action_limit_reached"
    with pytest.raises(RuntimeError, match="already stopped"):
        state.record_step(_step(4, "Autre question"))


def test_campaign_stops_at_global_timeout() -> None:
    limits = CampaignLimits(
        max_agent_steps=8,
        max_llm_calls_per_test=5,
        global_test_timeout_seconds=10,
        max_repeated_actions=2,
        min_evidence_confidence=0.8,
    )
    started_at = datetime(2026, 7, 28, tzinfo=UTC)
    state = CampaignState(
        run_id="RUN-1", trace_id="TRACE-1", test_case=_case(), limits=limits, started_at=started_at
    )

    assert state.evaluate_stop_condition(now=started_at + timedelta(seconds=10)) == "global_timeout_reached"


def test_jsonl_storage_redacts_secret_shaped_values_and_replays_events(tmp_path) -> None:
    store = JsonlTraceStore(tmp_path)
    event = models.TraceEvent(
        run_id="RUN-1",
        test_id="TEST-1",
        trace_id="TRACE-1",
        step_id="STEP-1",
        channel=models.Channel.API,
        event_type="api_call",
        source="executor",
        data={"endpoint": "/api/conversation/answer", "Authorization": "Bearer secret", "nested": {"api_key": "x"}},
    )

    path = store.append(event)
    persisted = path.read_text(encoding="utf-8")

    assert "Bearer secret" not in persisted
    assert '"[REDACTED]"' in persisted
    assert store.read("RUN-1", "TRACE-1")[0].data["Authorization"] == "[REDACTED]"
