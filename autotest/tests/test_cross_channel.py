"""API/Web comparison checks both values and PDF provenance."""

from __future__ import annotations

from datetime import UTC, datetime

from myfinance_autotest import models
from myfinance_autotest.validators.cross_channel import compare_api_and_web


def _case() -> models.TestCase:
    objective = models.TestObjective(
        objective_id="OBJ-CROSS-001",
        category=models.TestCategory.CROSS_CHANNEL,
        description="Comparer la réponse API avec son rendu Web.",
        required_properties=["same_value", "same_source"],
        rationale="Les deux canaux doivent exposer la même preuve financière.",
    )
    return models.TestCase(
        test_id="TEST-CROSS-001",
        title="PNB BIAT 2025 API et Web",
        category=models.TestCategory.CROSS_CHANNEL,
        channels=[models.Channel.API, models.Channel.WEB],
        input="Quel est le PNB de BIAT en 2025 ?",
        objective=objective,
        expected_properties=["same_value", "same_source"],
        failure_criteria=["channel_divergence"],
    )


def _execution(channel: models.Channel, response: dict) -> models.ToolExecutionResult:
    timestamp = datetime.now(UTC)
    return models.ToolExecutionResult(
        action_id=f"ACTION-{channel.value}",
        channel=channel,
        started_at=timestamp,
        finished_at=timestamp,
        latency_ms=10,
        http_status=200 if channel is models.Channel.API else None,
        response=response,
        visible_text="Réponse affichée" if channel is models.Channel.WEB else None,
    )


def _api_response() -> dict:
    return {
        "type": "numeric",
        "value": "1594799",
        "reporting_year": 2025,
        "page_number": 4,
        "source_excerpt": "Produit Net Bancaire 1 594 799",
        "source_document": "data/raw/official-reports/etat financier/biat/biat_efd311225.pdf",
    }


def test_cross_channel_passes_when_value_year_and_pdf_proof_match() -> None:
    web_response = {
        "type": "numeric",
        "value": "1\u202f594\u202f799",
        "reporting_year": 2025,
        "page_number": 4,
        "source_excerpt": "“Produit Net Bancaire 1 594 799”",
        "source_document": "biat_efd311225.pdf",
    }

    result = compare_api_and_web(
        _case(),
        _execution(models.Channel.API, _api_response()),
        _execution(models.Channel.WEB, web_response),
    )

    assert result.verdict is models.Verdict.PASS


def test_cross_channel_detects_a_source_page_divergence() -> None:
    web_response = {
        "type": "numeric",
        "value": "1 594 799",
        "reporting_year": 2025,
        "page_number": 5,
        "source_excerpt": "Produit Net Bancaire 1 594 799",
        "source_document": "biat_efd311225.pdf",
    }

    result = compare_api_and_web(
        _case(),
        _execution(models.Channel.API, _api_response()),
        _execution(models.Channel.WEB, web_response),
    )

    assert result.verdict is models.Verdict.FAIL
    assert models.FailureCategory.CHANNEL_DIVERGENCE in result.failure_categories
