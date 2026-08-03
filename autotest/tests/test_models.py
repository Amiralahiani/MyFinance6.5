"""Contract tests for the autonomous-testing state exchanged by all agents."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from myfinance_autotest import models
from pydantic import ValidationError


def _objective() -> models.TestObjective:
    return models.TestObjective(
        objective_id="OBJ-001",
        category=models.TestCategory.FINANCIAL_FACT,
        description="Vérifier une valeur financière, son année et sa source.",
        required_properties=["correct_year", "supported_by_source"],
        rationale="Le chiffre financier doit être traçable au PDF officiel.",
    )


def test_test_case_and_trace_event_are_json_serialisable() -> None:
    case = models.TestCase(
        test_id="TEST-001",
        title="PNB BIAT 2025",
        category=models.TestCategory.FINANCIAL_FACT,
        channels=[models.Channel.API, models.Channel.WEB],
        input="Quel est le PNB de BIAT en 2025 ?",
        objective=_objective(),
        bank_id="biat",
        reporting_year=2025,
        expected_properties=["correct_year", "supported_by_source", "correct_unit"],
        failure_criteria=["wrong_year", "unsupported_value"],
    )
    event = models.TraceEvent(
        run_id="RUN-001",
        test_id=case.test_id,
        trace_id="TRACE-001",
        step_id="STEP-001",
        channel=models.Channel.API,
        event_type="action_planned",
        source="planner",
        data={"objective_id": case.objective.objective_id},
    )

    assert models.TestCase.model_validate_json(case.model_dump_json()) == case
    assert models.TraceEvent.model_validate_json(event.model_dump_json()) == event


def test_evaluator_scores_are_bounded_and_require_a_rationale() -> None:
    base = {
        "test_id": "TEST-001",
        "verdict": models.Verdict.PASS,
        "relevance": 5,
        "factuality": 5,
        "source_fidelity": 5,
        "conversation_coherence": 5,
        "year_respect": 5,
        "unit_respect": 5,
        "clarity": 5,
        "format_respect": 5,
        "confidence": 0.95,
        "rationale": "Les contrôles déterministes et la source concordent.",
    }

    assert models.EvaluationResult.model_validate(base).verdict is models.Verdict.PASS
    with pytest.raises(ValidationError):
        models.EvaluationResult.model_validate({**base, "factuality": 6})


def test_trace_event_preserves_correlation_identifiers() -> None:
    event = models.TraceEvent(
        run_id="RUN-001",
        test_id="TEST-001",
        trace_id="TRACE-001",
        step_id="STEP-004",
        parent_step_id="STEP-003",
        session_id="SESSION-001",
        timestamp=datetime(2026, 7, 28, tzinfo=UTC),
        channel=models.Channel.WEB,
        event_type="rag_retrieval",
        source="backend",
        data={"document": "biat-2025", "page": 4, "score": 0.91},
    )

    assert event.parent_step_id == "STEP-003"
    assert event.data["page"] == 4
