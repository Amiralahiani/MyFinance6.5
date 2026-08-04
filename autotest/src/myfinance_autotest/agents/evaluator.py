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
The deterministic validation and PDF evidence are authoritative: never dispute
them and never invent evidence or citations. Return exactly one JSON object,
with every key below and no Markdown:
{
  "relevance": 1-5, "factuality": 1-5, "source_fidelity": 1-5,
  "conversation_coherence": 1-5, "year_respect": 1-5,
  "unit_respect": 1-5, "clarity": 1-5, "format_respect": 1-5,
  "failure_category": null or one deterministic failure category,
  "probable_cause": null or a concise English string,
  "confidence": 0.0-1.0, "rationale": "concise English explanation"
}
Every score must be an integer. Keep the two text fields concise."""


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
        rationale="Qualitative evaluation unavailable; deterministic verdict retained.",
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
                "question": test_case.input,
                "expected_properties": test_case.expected_properties,
                "failure_criteria": test_case.failure_criteria,
                "api_response": execution.response,
                "deterministic_verdict": validation.verdict.value,
                "failure_categories": [category.value for category in validation.failure_categories],
                "failed_checks": [
                    {"name": check.name, "expected": check.expected, "actual": check.actual}
                    for check in validation.checks
                    if check.passed is False
                ],
            },
            ensure_ascii=False,
        ),
        response_model=EvaluatorOpinion,
        campaign=campaign,
        max_completion_tokens=220,
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
