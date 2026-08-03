"""Final deterministic verdicts for autonomous test executions."""

from __future__ import annotations

from myfinance_autotest.agents.grounding import ground_financial_answer
from myfinance_autotest.models import (
    DeterministicCheck,
    DeterministicValidationResult,
    FailureCategory,
    GroundingStatus,
    TestCase,
    TestCategory,
    ToolExecutionResult,
    Verdict,
)

_GROUNDING_FAILURES = {
    "metric_id_matches_evidence": FailureCategory.UNSUPPORTED_VALUE,
    "value_matches_evidence": FailureCategory.UNSUPPORTED_VALUE,
    "reporting_year_matches_evidence": FailureCategory.WRONG_YEAR,
    "currency_matches_evidence": FailureCategory.WRONG_UNIT,
    "unit_scale_matches_evidence": FailureCategory.WRONG_UNIT,
    "source_document_matches_evidence": FailureCategory.SOURCE_MISMATCH,
    "page_matches_evidence": FailureCategory.SOURCE_MISMATCH,
    "source_excerpt_matches_evidence": FailureCategory.SOURCE_MISMATCH,
}


def validate_deterministically(
    test_case: TestCase,
    execution: ToolExecutionResult,
    technical_checks: list[DeterministicCheck],
) -> DeterministicValidationResult:
    """Combine transport checks with mandatory PDF grounding for financial facts.

    A test without an expected auto-validated fact is *inconclusive*: it is a
    data-coverage gap, not a false PASS and not a fabricated financial oracle.
    """

    checks = list(technical_checks)
    failure_categories: list[FailureCategory] = []
    if any(check.passed is False for check in technical_checks):
        failure_categories.append(FailureCategory.API_ERROR)

    grounding = None
    if test_case.category is TestCategory.FINANCIAL_FACT:
        grounding = ground_financial_answer(test_case, execution)
        checks.extend(grounding.checks)
        if grounding.status is GroundingStatus.MISSING_EXPECTED_FACT:
            failure_categories.append(FailureCategory.INSUFFICIENT_EVIDENCE)
        elif grounding.status is GroundingStatus.INCONCLUSIVE:
            failure_categories.append(FailureCategory.UNDETERMINED)
        elif grounding.status is GroundingStatus.RESPONSE_MISMATCH:
            for check in grounding.checks:
                if check.passed is False and check.name in _GROUNDING_FAILURES:
                    failure_categories.append(_GROUNDING_FAILURES[check.name])

    # Keep the report compact and stable while preserving the first occurrence.
    unique_failures = list(dict.fromkeys(failure_categories))
    if grounding and grounding.status in {
        GroundingStatus.MISSING_EXPECTED_FACT,
        GroundingStatus.INCONCLUSIVE,
    }:
        verdict = Verdict.INCONCLUSIVE
    elif any(check.passed is False for check in checks):
        verdict = Verdict.FAIL
    else:
        verdict = Verdict.PASS
    return DeterministicValidationResult(
        test_id=test_case.test_id,
        verdict=verdict,
        checks=checks,
        grounding=grounding,
        failure_categories=unique_failures,
    )


def validate_expected_absence(
    test_case: TestCase,
    execution: ToolExecutionResult,
    technical_checks: list[DeterministicCheck],
) -> DeterministicValidationResult:
    """Pass only when a known unavailable fact is explicitly not invented."""

    grounding = ground_financial_answer(test_case, execution)
    response = execution.response or {}
    message = str(response.get("message", "")).lower()
    checks = [
        *technical_checks,
        DeterministicCheck(
            check_id="absence.fact_is_unavailable",
            name="expected_auto_validated_fact_is_unavailable",
            passed=grounding.status is GroundingStatus.MISSING_EXPECTED_FACT,
            expected="missing_expected_fact",
            actual=grounding.status.value,
        ),
        DeterministicCheck(
            check_id="absence.response_type",
            name="absence_returns_clarification",
            passed=response.get("type") == "clarification",
            expected="clarification",
            actual=response.get("type"),
        ),
        DeterministicCheck(
            check_id="absence.value",
            name="absence_does_not_invent_a_value",
            passed="value" not in response,
            expected="no value field",
            actual=response.get("value"),
        ),
        DeterministicCheck(
            check_id="absence.message",
            name="absence_explains_the_validation_gap",
            passed="validation automatique" in message,
            expected="message mentions validation automatique",
            actual=response.get("message"),
        ),
    ]
    failed = any(check.passed is False for check in checks)
    return DeterministicValidationResult(
        test_id=test_case.test_id,
        verdict=Verdict.FAIL if failed else Verdict.PASS,
        checks=checks,
        grounding=grounding,
        failure_categories=[FailureCategory.UNSUPPORTED_VALUE] if failed else [],
    )


def validate_behavior_contract(
    test_case: TestCase,
    execution: ToolExecutionResult,
    technical_checks: list[DeterministicCheck],
) -> DeterministicValidationResult:
    """Validate observable conversation and document contracts without an invented answer oracle."""
    response = execution.response or {}
    visible_text = execution.visible_text or ""
    message = str(response.get("message", ""))
    normalized_message = message.lower()
    checks = list(technical_checks)
    failure_categories: list[FailureCategory] = []
    for expected in test_case.expected_properties:
        if expected.startswith("response_type:"):
            expected_type = expected.split(":", 1)[1]
            checks.append(DeterministicCheck(
                check_id=f"behavior.{expected_type}.response_type", name="response_type_matches_contract",
                passed=response.get("type") == expected_type, expected=expected_type, actual=response.get("type"),
            ))
        elif expected == "no_numeric_value":
            check = DeterministicCheck(
                check_id="behavior.no_numeric_value", name="does_not_invent_numeric_value",
                passed="value" not in response, expected="no value field", actual=response.get("value"),
            )
            checks.append(check)
            if check.passed is False:
                failure_categories.append(FailureCategory.UNSUPPORTED_VALUE)
        elif expected == "evidence_present":
            checks.append(DeterministicCheck(
                check_id="behavior.evidence_present", name="documentary_evidence_is_present",
                passed=bool(response.get("evidence")), expected="at least one evidence item", actual=len(response.get("evidence", [])),
            ))
        elif expected.startswith("message_contains:"):
            fragment = expected.split(":", 1)[1].lower()
            checks.append(DeterministicCheck(
                check_id=f"behavior.message.{fragment}", name="message_contains_expected_guidance",
                passed=fragment in message.lower(), expected=fragment, actual=message,
            ))
        elif expected == "asks_for_single_bank":
            check = DeterministicCheck(
                check_id="behavior.single_bank", name="asks_user_to_choose_one_bank",
                passed=any(fragment in normalized_message for fragment in ("une seule banque", "choisir une banque", "quelle banque", "la banque à analyser")),
                expected="explicit request to choose one bank", actual=message,
            )
            checks.append(check)
            if check.passed is False:
                failure_categories.append(FailureCategory.CONTRACT_VIOLATION)
        elif expected == "states_year_unavailable":
            check = DeterministicCheck(
                check_id="behavior.unavailable_year", name="states_that_the_requested_year_is_not_available",
                passed="année" in normalized_message and any(fragment in normalized_message for fragment in ("disponible", "rapport", "non couvert", "n'existe pas")),
                expected="explains that the requested year is unavailable", actual=message,
            )
            checks.append(check)
            if check.passed is False:
                failure_categories.append(FailureCategory.WRONG_YEAR)
        elif expected == "refuses_personal_account_access":
            check = DeterministicCheck(
                check_id="behavior.personal_account_scope", name="states_no_access_to_personal_account_data",
                passed=("compte" in normalized_message or "donnée personnelle" in normalized_message) and any(fragment in normalized_message for fragment in ("pas accès", "ne peux pas consulter", "n'ai pas accès", "ne dispose pas")),
                expected="explicitly states no access to personal account data", actual=message,
            )
            checks.append(check)
            if check.passed is False:
                failure_categories.append(FailureCategory.PERSONAL_DATA_SCOPE)
        elif expected == "refuses_unsupported_ranking":
            check = DeterministicCheck(
                check_id="behavior.ranking_scope", name="refuses_an_unsupported_bank_ranking",
                passed=any(fragment in normalized_message for fragment in ("ne peux pas", "je ne peux pas", "sans critère", "critère")),
                expected="refuses ranking without a defined criterion", actual=message,
            )
            checks.append(check)
            if check.passed is False:
                failure_categories.append(FailureCategory.UNSUPPORTED_COMPARISON)
        elif expected == "refuses_unsupported_conversion":
            check = DeterministicCheck(
                check_id="behavior.currency_scope", name="refuses_currency_conversion_without_a_sourced_rate",
                passed=any(fragment in normalized_message for fragment in ("taux de change", "conversion", "devise")) and "value" not in response,
                expected="no converted value without a sourced exchange rate", actual={"message": message, "value": response.get("value")},
            )
            checks.append(check)
            if check.passed is False:
                failure_categories.append(FailureCategory.UNSUPPORTED_CONVERSION)
        elif expected.startswith("visible_contains:"):
            fragment = expected.split(":", 1)[1].lower()
            checks.append(DeterministicCheck(
                check_id=f"behavior.visible.{fragment}", name="web_response_contains_expected_guidance",
                passed=fragment in visible_text.lower(), expected=fragment, actual=visible_text,
            ))
    failed = any(check.passed is False for check in checks)
    if failed and not failure_categories:
        failure_categories.append(FailureCategory.CONTRACT_VIOLATION)
    return DeterministicValidationResult(
        test_id=test_case.test_id,
        verdict=Verdict.FAIL if failed else Verdict.PASS,
        checks=checks,
        failure_categories=list(dict.fromkeys(failure_categories)),
    )
