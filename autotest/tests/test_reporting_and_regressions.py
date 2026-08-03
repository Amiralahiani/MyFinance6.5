"""Reports are readable; regressions are evidence-backed and deduplicated."""

from __future__ import annotations

from myfinance_autotest import models
from myfinance_autotest.regressions.registry import (
    RegressionRegistry,
    regression_from_confirmed_defect,
)
from myfinance_autotest.reporting.rendered_report import write_rendered_api_report


def _case() -> models.TestCase:
    objective = models.TestObjective(
        objective_id="OBJ-REPORT-001",
        category=models.TestCategory.FINANCIAL_FACT,
        description="Produire un rapport de validation financier lisible.",
        required_properties=["source_fidelity"],
        rationale="Une anomalie prouvée doit devenir rejouable.",
    )
    return models.TestCase(
        test_id="TEST-REPORT-001",
        title="Erreur année PNB BIAT",
        category=models.TestCategory.FINANCIAL_FACT,
        channels=[models.Channel.API],
        input="Quel est le PNB de BIAT en 2025 ?",
        objective=objective,
        bank_id="biat",
        reporting_year=2025,
        metric_id="net_banking_income",
        expected_properties=["source_fidelity"],
        failure_criteria=["wrong_year"],
    )


def _validation() -> models.DeterministicValidationResult:
    evidence = models.RetrievedEvidence(
        document_id="biat-2025",
        source_path="data/raw/biat-2025.pdf",
        page_number=4,
        excerpt="Produit net bancaire 1 594 799",
        metric_id="net_banking_income",
        reporting_year=2025,
        unit_scale="thousand",
        value="1594799",
        evidence_kind="auto_validated_fact",
    )
    grounding = models.GroundingResult(
        test_id="TEST-REPORT-001",
        status=models.GroundingStatus.RESPONSE_MISMATCH,
        expected_bank_id="biat",
        expected_reporting_year=2025,
        expected_metric_id="net_banking_income",
        evidence=[evidence],
    )
    return models.DeterministicValidationResult(
        test_id="TEST-REPORT-001",
        verdict=models.Verdict.FAIL,
        checks=[
            models.DeterministicCheck(
                check_id="year",
                name="reporting_year_matches_evidence",
                passed=False,
                expected=2025,
                actual=2024,
            )
        ],
        grounding=grounding,
        failure_categories=[models.FailureCategory.WRONG_YEAR],
    )


def _critic() -> models.CriticDecision:
    return models.CriticDecision(
        decision_id="CRITIC-001",
        verdict_confirmed=True,
        next_action_required=False,
        create_regression_test=True,
        reason="L'année retournée diverge de la preuve PDF.",
        confidence=1.0,
    )


def test_registry_creates_once_then_deduplicates_the_same_proven_defect(tmp_path) -> None:
    regression = regression_from_confirmed_defect(_case(), _validation(), _critic())
    assert regression is not None
    registry = RegressionRegistry(tmp_path)

    first = registry.register(regression)
    second = registry.register(regression)

    assert first.created
    assert not second.created
    assert first.path.exists()


def test_regression_can_capture_a_confirmed_conversation_contract_failure() -> None:
    case = _case().model_copy(update={"test_id": "EXPLORE-SCOPE", "category": models.TestCategory.CONVERSATION})
    validation = models.DeterministicValidationResult(
        test_id=case.test_id,
        verdict=models.Verdict.FAIL,
        checks=[],
        failure_categories=[models.FailureCategory.PERSONAL_DATA_SCOPE],
    )
    critic = _critic().model_copy(update={"decision_id": "CRITIC-SCOPE"})

    regression = regression_from_confirmed_defect(case, validation, critic)

    assert regression is not None
    assert regression.evidence == []
    assert regression.failure_category is models.FailureCategory.PERSONAL_DATA_SCOPE


def test_reporter_writes_markdown_and_html_with_the_pdf_evidence(tmp_path) -> None:
    validation = _validation()
    report = models.ApiPrototypeReport(
        run_id="RUN-REPORT",
        trace_id="TRACE-REPORT",
        test_id="TEST-REPORT-001",
        endpoint="http://127.0.0.1:8000/api/conversation/answer",
        verdict=models.Verdict.FAIL,
        duration_ms=17,
        checks=validation.checks,
        grounding=validation.grounding,
        failure_categories=validation.failure_categories,
        response={"type": "numeric", "reporting_year": 2024},
        errors=[],
        trace_path="data/autotest/traces/RUN-REPORT.jsonl",
    )

    markdown_path, html_path = write_rendered_api_report(report, tmp_path)

    assert "ERREUR" not in markdown_path.read_text(encoding="utf-8")
    assert "data/raw/biat-2025.pdf" in markdown_path.read_text(encoding="utf-8")
    assert "wrong_year" in markdown_path.read_text(encoding="utf-8")
    assert "Produit net bancaire" in html_path.read_text(encoding="utf-8")
