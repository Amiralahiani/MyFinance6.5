"""Tests for the PDF-backed Financial Grounding component."""

from datetime import UTC, datetime

from myfinance_agent_docs.facts import auto_validated_fact
from myfinance_autotest.agents.grounding import ground_financial_answer
from myfinance_autotest.models import (
    Channel,
    GroundingStatus,
    ToolExecutionResult,
)
from myfinance_autotest.models import (
    TestCase as AutotestCase,
)
from myfinance_autotest.models import (
    TestCategory as AutotestCategory,
)
from myfinance_autotest.models import (
    TestObjective as AutotestObjective,
)


def _case(**overrides) -> AutotestCase:
    objective = AutotestObjective(
        objective_id="OBJ-GROUNDING-001",
        category=AutotestCategory.FINANCIAL_FACT,
        description="Comparer une réponse financière avec le fait PDF validé.",
        required_properties=["source_fidelity"],
        rationale="La preuve doit venir d'un fait auto-validé.",
    )
    values = {
        "test_id": "TEST-GROUNDING-BIAT-PNB-2025",
        "title": "PNB BIAT 2025 avec preuve PDF",
        "category": AutotestCategory.FINANCIAL_FACT,
        "channels": [Channel.API],
        "input": "Quel est le PNB de BIAT en 2025 ?",
        "objective": objective,
        "bank_id": "biat",
        "reporting_year": 2025,
        "metric_id": "net_banking_income",
        "expected_properties": ["source_fidelity"],
        "failure_criteria": ["unsupported_value", "source_mismatch"],
    }
    values.update(overrides)
    return AutotestCase(**values)


def _execution(response: dict) -> ToolExecutionResult:
    timestamp = datetime.now(UTC)
    return ToolExecutionResult(
        action_id="ACTION-ANSWER",
        channel=Channel.API,
        started_at=timestamp,
        finished_at=timestamp,
        latency_ms=17,
        http_status=200,
        response=response,
    )


def _matching_response() -> dict:
    fact = auto_validated_fact("biat", 2025, "net_banking_income")
    assert fact is not None
    return {
        "type": "numeric",
        "metric_id": fact.metric_id,
        "value": str(fact.value),
        "currency": fact.currency,
        "unit_scale": fact.unit_scale,
        "reporting_year": fact.reporting_year,
        "source_document": fact.source_path,
        "page_number": fact.page_number,
        "source_excerpt": fact.source_excerpt,
    }


def test_grounding_verifies_a_pdf_backed_numeric_answer() -> None:
    result = ground_financial_answer(_case(), _execution(_matching_response()))

    assert result.status is GroundingStatus.VERIFIED
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_kind == "auto_validated_fact"
    assert all(check.passed for check in result.checks)


def test_grounding_detects_a_mismatched_reporting_year() -> None:
    response = _matching_response()
    response["reporting_year"] = 2024

    result = ground_financial_answer(_case(), _execution(response))

    assert result.status is GroundingStatus.RESPONSE_MISMATCH
    year_check = next(
        check for check in result.checks if check.name == "reporting_year_matches_evidence"
    )
    assert not year_check.passed


def test_grounding_reports_missing_facts_without_fabricating_evidence() -> None:
    result = ground_financial_answer(
        _case(
            test_id="TEST-GROUNDING-ZITOUNA-NET-INCOME-2021",
            input="Quel est le résultat net de Zitouna en 2021 ?",
            bank_id="zitouna",
            reporting_year=2021,
            metric_id="net_income",
        ),
        _execution({"type": "numeric", "value": "123"}),
    )

    assert result.status is GroundingStatus.MISSING_EXPECTED_FACT
    assert result.evidence == []
    assert any(
        check.name == "expected_auto_validated_fact_exists" and not check.passed
        for check in result.checks
    )
