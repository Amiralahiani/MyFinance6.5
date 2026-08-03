"""Groq quality scoring that cannot override deterministic financial validation."""

from __future__ import annotations

import json

from myfinance_autotest.models import (
    DeterministicValidationResult,
    EvaluationResult,
    EvaluatorOpinion,
    TestCase,
    ToolExecutionResult,
    Verdict,
)
from myfinance_autotest.state import CampaignState
from myfinance_autotest.tools.groq_client import GroqCallResult, GroqClient

_SYSTEM_PROMPT = """You are a quality evaluator for a banking conversation test.
Score only the relevance, clarity and consistency of the response from 1 to 5.
The deterministic validation and PDF evidence are authoritative: do not claim a
financial value is correct when a deterministic check says otherwise. Return
  only JSON that matches the schema. Do not invent evidence or citations. Keep
the rationale and probable cause concise."""


def _fallback(test_case: TestCase, validation: DeterministicValidationResult) -> EvaluationResult:
    score = 5 if validation.verdict is Verdict.PASS else 1 if validation.verdict is Verdict.FAIL else 3
    return EvaluationResult(
        test_id=test_case.test_id,
        verdict=validation.verdict,
        relevance=score,
        factuality=score,
        source_fidelity=score,
        conversation_coherence=score,
        year_respect=score,
        unit_respect=score,
        clarity=score,
        format_respect=score,
        failure_category=(validation.failure_categories[0] if validation.failure_categories else None),
        probable_cause=None,
        confidence=1.0,
        evidence=validation.grounding.evidence if validation.grounding else [],
        deterministic_checks=validation.checks,
        rationale="Évaluation qualitative indisponible ; verdict déterministe conservé.",
    )


def evaluate_response(
    test_case: TestCase,
    execution: ToolExecutionResult,
    validation: DeterministicValidationResult,
    *,
    client: GroqClient,
    campaign: CampaignState,
) -> tuple[EvaluationResult, GroqCallResult]:
    """Request a structured quality opinion, then bind it to local proof/verdict."""

    opinion, metadata = client.complete_json(
        role="evaluator",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=json.dumps(
            {
                "test_case": test_case.model_dump(mode="json"),
                "api_response": execution.response,
                "deterministic_validation": validation.model_dump(mode="json"),
            },
            ensure_ascii=False,
        ),
        response_model=EvaluatorOpinion,
        campaign=campaign,
        max_completion_tokens=320,
    )
    if opinion is None:
        return _fallback(test_case, validation), metadata

    scores = [
        opinion.relevance,
        opinion.factuality,
        opinion.source_fidelity,
        opinion.conversation_coherence,
        opinion.year_respect,
        opinion.unit_respect,
        opinion.clarity,
        opinion.format_respect,
    ]
    # Code validation always wins. A low qualitative score can downgrade only a
    # technically sound response to WARNING, never invent a deterministic FAIL.
    if validation.verdict is Verdict.FAIL:
        verdict = Verdict.FAIL
    elif validation.verdict is Verdict.INCONCLUSIVE:
        verdict = Verdict.INCONCLUSIVE
    elif min(scores) < 3:
        verdict = Verdict.WARNING
    else:
        verdict = Verdict.PASS
    return (
        EvaluationResult(
            test_id=test_case.test_id,
            verdict=verdict,
            relevance=opinion.relevance,
            factuality=opinion.factuality,
            source_fidelity=opinion.source_fidelity,
            conversation_coherence=opinion.conversation_coherence,
            year_respect=opinion.year_respect,
            unit_respect=opinion.unit_respect,
            clarity=opinion.clarity,
            format_respect=opinion.format_respect,
            failure_category=(validation.failure_categories[0] if validation.failure_categories else opinion.failure_category),
            probable_cause=opinion.probable_cause,
            confidence=opinion.confidence,
            evidence=validation.grounding.evidence if validation.grounding else [],
            deterministic_checks=validation.checks,
            rationale=opinion.rationale,
        ),
        metadata,
    )
