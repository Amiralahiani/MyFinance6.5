"""Tests for the final code-based verdict, including financial grounding."""

from datetime import UTC, datetime

from myfinance_agent_docs.facts import auto_validated_fact
from myfinance_autotest import models
from myfinance_autotest.validators.deterministic import (
    validate_behavior_contract,
    validate_deterministically,
)


def _case() -> models.TestCase:
    objective = models.TestObjective(
        objective_id="OBJ-VALIDATOR-001",
        category=models.TestCategory.FINANCIAL_FACT,
        description="Valider une réponse financière avec son origine PDF.",
        required_properties=["source_fidelity"],
        rationale="La réponse doit provenir d'un fait auto-validé.",
    )
    return models.TestCase(
        test_id="TEST-VALIDATOR-001",
        title="Contrôle déterministe du PNB BIAT 2025",
        category=models.TestCategory.FINANCIAL_FACT,
        channels=[models.Channel.API],
        input="Quel est le PNB de BIAT en 2025 ?",
        objective=objective,
        bank_id="biat",
        reporting_year=2025,
        metric_id="net_banking_income",
        expected_properties=["source_fidelity"],
        failure_criteria=["unsupported_value"],
    )


def _execution(response: dict) -> models.ToolExecutionResult:
    timestamp = datetime.now(UTC)
    return models.ToolExecutionResult(
        action_id="ACTION-001",
        channel=models.Channel.API,
        started_at=timestamp,
        finished_at=timestamp,
        latency_ms=11,
        http_status=200,
        response=response,
    )


def _technical_success() -> list[models.DeterministicCheck]:
    return [
        models.DeterministicCheck(
            check_id="http",
            name="http_status_is_success",
            passed=True,
            expected=200,
            actual=200,
        )
    ]


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


def test_validator_passes_only_when_transport_and_pdf_evidence_match() -> None:
    result = validate_deterministically(_case(), _execution(_matching_response()), _technical_success())

    assert result.verdict is models.Verdict.PASS
    assert result.failure_categories == []


def test_validator_fails_an_answer_with_the_wrong_year() -> None:
    response = _matching_response()
    response["reporting_year"] = 2024

    result = validate_deterministically(_case(), _execution(response), _technical_success())

    assert result.verdict is models.Verdict.FAIL
    assert models.FailureCategory.WRONG_YEAR in result.failure_categories


def test_validator_marks_absent_validated_data_as_inconclusive() -> None:
    missing = _case().model_copy(
        update={
            "test_id": "TEST-VALIDATOR-MISSING",
            "bank_id": "zitouna",
            "reporting_year": 2021,
            "metric_id": "cash_and_central_bank",
            "input": "Quel est le montant de caisse de Zitouna en 2021 ?",
        }
    )

    result = validate_deterministically(
        missing,
        _execution({"type": "numeric", "value": "123"}),
        _technical_success(),
    )

    assert result.verdict is models.Verdict.INCONCLUSIVE
    assert models.FailureCategory.INSUFFICIENT_EVIDENCE in result.failure_categories


def test_behavior_validator_fails_a_currency_conversion_without_a_sourced_rate() -> None:
    scenario = _case().model_copy(
        update={
            "test_id": "EXPLORE-UNIT-TRAP",
            "category": models.TestCategory.CONVERSATION,
            "expected_properties": ["response_type:clarification", "no_numeric_value", "refuses_unsupported_conversion"],
            "origin": "groq_exploration_generator",
        }
    )

    result = validate_behavior_contract(
        scenario,
        _execution({"type": "numeric", "value": "385264", "message": "Voici le résultat en TND."}),
        _technical_success(),
    )

    assert result.verdict is models.Verdict.FAIL
    assert models.FailureCategory.UNSUPPORTED_CONVERSION in result.failure_categories


def test_behavior_validator_requires_explicit_personal_account_scope() -> None:
    scenario = _case().model_copy(
        update={
            "test_id": "EXPLORE-PERSONAL-ACCOUNT",
            "category": models.TestCategory.CONVERSATION,
            "expected_properties": ["response_type:clarification", "no_numeric_value", "refuses_personal_account_access"],
            "origin": "groq_exploration_generator",
        }
    )

    result = validate_behavior_contract(
        scenario,
        _execution({"type": "clarification", "message": "Indiquez la banque et l'année."}),
        _technical_success(),
    )

    assert result.verdict is models.Verdict.FAIL
    assert models.FailureCategory.PERSONAL_DATA_SCOPE in result.failure_categories


def test_behavior_validator_accepts_a_safe_market_notice_when_the_quote_is_unavailable() -> None:
    scenario = _case().model_copy(
        update={
            "test_id": "BEHAVIOR-MARKET-CURRENT",
            "category": models.TestCategory.TEMPORAL,
            "expected_properties": ["response_type_any:market_quote|market_notice", "response_mode:market"],
            "origin": "catalog_behavior_contract",
        }
    )

    result = validate_behavior_contract(
        scenario,
        _execution({"type": "market_notice", "mode": "market", "message": "Official quote unavailable."}),
        _technical_success(),
    )

    assert result.verdict is models.Verdict.PASS


def test_behavior_validator_requires_a_general_source_or_a_verified_refusal() -> None:
    scenario = _case().model_copy(
        update={
            "test_id": "BEHAVIOR-GENERAL-OFFICIAL-SOURCES",
            "category": models.TestCategory.SOURCE,
            "expected_properties": ["response_type:general", "official_source_or_verified_refusal"],
            "origin": "catalog_behavior_contract",
        }
    )

    result = validate_behavior_contract(
        scenario,
        _execution({"type": "general", "source_status": "official_source_required", "sources": []}),
        _technical_success(),
    )

    assert result.verdict is models.Verdict.PASS
