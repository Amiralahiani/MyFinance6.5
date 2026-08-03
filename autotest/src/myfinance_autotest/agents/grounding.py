"""Financial grounding based only on auto-validated report facts.

No LLM is asked to judge a financial answer here.  The component retrieves the
expected fact from the validated data store and compares each material response
field with the fact and its recorded PDF provenance.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from myfinance_agent_docs.facts import auto_validated_fact
from myfinance_orchestrator.assessment import assess_request

from ..models import (
    DeterministicCheck,
    GroundingResult,
    GroundingStatus,
    RetrievedEvidence,
    TestCase,
    ToolExecutionResult,
)


def _check(name: str, expected: Any, actual: Any, *, detail: str = "") -> DeterministicCheck:
    return DeterministicCheck(
        check_id=f"grounding.{name}",
        name=name,
        passed=expected == actual,
        expected=expected,
        actual=actual,
        detail=detail,
    )


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _resolved_identity(test_case: TestCase) -> tuple[str | None, int | None, str | None]:
    """Prefer explicit test metadata and only then parse the test question."""

    assessment = assess_request(test_case.input)
    bank_id = test_case.bank_id or (assessment.detected_banks[0] if assessment.detected_banks else None)
    reporting_year = test_case.reporting_year or (
        assessment.detected_years[0] if assessment.detected_years else None
    )
    metric_id = test_case.metric_id or assessment.detected_metric
    return bank_id, reporting_year, metric_id


def ground_financial_answer(test_case: TestCase, execution: ToolExecutionResult) -> GroundingResult:
    """Return source evidence and deterministic comparisons for one financial answer.

    When a fact is not auto-validated, the result says so explicitly and returns
    no evidence.  It never substitutes a guessed value or fabricated citation.
    """

    bank_id, reporting_year, metric_id = _resolved_identity(test_case)
    identity_complete = bank_id is not None and reporting_year is not None and metric_id is not None
    checks = [
        DeterministicCheck(
            check_id="grounding.expected_financial_identity_is_complete",
            name="expected_financial_identity_is_complete",
            passed=identity_complete,
            expected="bank_id, reporting_year and metric_id",
            actual={
                "bank_id": bank_id,
                "reporting_year": reporting_year,
                "metric_id": metric_id,
            },
        )
    ]
    if not identity_complete:
        return GroundingResult(
            test_id=test_case.test_id,
            status=GroundingStatus.INCONCLUSIVE,
            expected_bank_id=bank_id,
            expected_reporting_year=reporting_year,
            expected_metric_id=metric_id,
            checks=checks,
        )

    fact = auto_validated_fact(bank_id, reporting_year, metric_id)
    if fact is None:
        checks.append(
            DeterministicCheck(
                check_id="grounding.expected_auto_validated_fact_exists",
                name="expected_auto_validated_fact_exists",
                passed=False,
                expected={
                    "bank_id": bank_id,
                    "reporting_year": reporting_year,
                    "metric_id": metric_id,
                },
                actual=None,
                detail="No auto-validated fact exists; no evidence may be invented.",
            )
        )
        return GroundingResult(
            test_id=test_case.test_id,
            status=GroundingStatus.MISSING_EXPECTED_FACT,
            expected_bank_id=bank_id,
            expected_reporting_year=reporting_year,
            expected_metric_id=metric_id,
            checks=checks,
        )

    evidence = RetrievedEvidence(
        document_id=fact.document_id,
        source_path=fact.source_path,
        page_number=fact.page_number,
        excerpt=fact.source_excerpt,
        metric_id=fact.metric_id,
        reporting_year=fact.reporting_year,
        unit_scale=fact.unit_scale,
        value=str(fact.value),
        evidence_kind="auto_validated_fact",
    )
    response = execution.response or {}
    checks.extend(
        [
            _check("response_type_is_numeric", "numeric", response.get("type")),
            _check("metric_id_matches_evidence", fact.metric_id, response.get("metric_id")),
            _check("value_matches_evidence", _decimal(fact.value), _decimal(response.get("value"))),
            _check(
                "reporting_year_matches_evidence", fact.reporting_year, response.get("reporting_year")
            ),
            _check("currency_matches_evidence", fact.currency, response.get("currency")),
            _check("unit_scale_matches_evidence", fact.unit_scale, response.get("unit_scale")),
            _check("source_document_matches_evidence", fact.source_path, response.get("source_document")),
            _check("page_matches_evidence", fact.page_number, response.get("page_number")),
            _check("source_excerpt_matches_evidence", fact.source_excerpt, response.get("source_excerpt")),
        ]
    )
    return GroundingResult(
        test_id=test_case.test_id,
        status=(
            GroundingStatus.VERIFIED
            if all(check.passed for check in checks)
            else GroundingStatus.RESPONSE_MISMATCH
        ),
        expected_bank_id=bank_id,
        expected_reporting_year=reporting_year,
        expected_metric_id=metric_id,
        evidence=[evidence],
        checks=checks,
    )
