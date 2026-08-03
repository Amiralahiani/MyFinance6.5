"""Critic decisions constrained by confirmed deterministic evidence."""

from __future__ import annotations

import json

from myfinance_autotest.models import (
    CriticDecision,
    CriticOpinion,
    DeterministicValidationResult,
    EvaluationResult,
    FailureCategory,
    TestCase,
    Verdict,
)
from myfinance_autotest.state import CampaignState
from myfinance_autotest.tools.groq_client import GroqCallResult, GroqClient

_SYSTEM_PROMPT = """You are a critic reviewing a banking conversation evaluation.
When a response is unsafe, unclear or insufficiently evidenced, propose at most
one short French follow-up question that can confirm the problem. Set
next_action_required only when that follow-up is useful. Never dispute
deterministic checks and do not create regressions yourself. Return only JSON
  matching the schema. Keep the reason and follow-up concise."""


def _is_confirmed_business_defect(validation: DeterministicValidationResult) -> bool:
    return validation.verdict is Verdict.FAIL and any(
        category
        in {
            FailureCategory.WRONG_BANK,
            FailureCategory.WRONG_YEAR,
            FailureCategory.WRONG_UNIT,
            FailureCategory.UNSUPPORTED_VALUE,
            FailureCategory.SOURCE_MISMATCH,
            FailureCategory.ARITHMETIC_ERROR,
            FailureCategory.CONTEXT_LOSS,
            FailureCategory.CHANNEL_DIVERGENCE,
            FailureCategory.CONTRACT_VIOLATION,
            FailureCategory.PERSONAL_DATA_SCOPE,
            FailureCategory.UNSUPPORTED_COMPARISON,
            FailureCategory.UNSUPPORTED_CONVERSION,
        }
        for category in validation.failure_categories
    )


def critique_evaluation(
    test_case: TestCase,
    evaluation: EvaluationResult,
    validation: DeterministicValidationResult,
    *,
    client: GroqClient,
    campaign: CampaignState,
) -> tuple[CriticDecision, GroqCallResult]:
    """Produce a bounded next-step decision and a regression eligibility flag."""

    opinion, metadata = client.complete_json(
        role="critic",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=json.dumps(
            {
                "test_case": test_case.model_dump(mode="json"),
                "evaluation": evaluation.model_dump(mode="json"),
                "deterministic_validation": validation.model_dump(mode="json"),
            },
            ensure_ascii=False,
        ),
        response_model=CriticOpinion,
        campaign=campaign,
        max_completion_tokens=400,
    )
    confirmed_defect = _is_confirmed_business_defect(validation)
    if opinion is None:
        return (
            CriticDecision(
                decision_id=f"{test_case.test_id}-CRITIC-{campaign.llm_call_count:02d}",
                verdict_confirmed=validation.verdict in {Verdict.PASS, Verdict.FAIL},
                next_action_required=False,
                create_regression_test=confirmed_defect,
                reason="Critique Groq indisponible ; décision déterministe conservée.",
                confidence=1.0,
            ),
            metadata,
        )

    may_follow_up = (
        opinion.next_action_required
        and validation.verdict is not Verdict.PASS
        and len(campaign.steps) < campaign.limits.max_agent_steps
        and bool(opinion.follow_up_question)
    )
    return (
        CriticDecision(
            decision_id=f"{test_case.test_id}-CRITIC-{campaign.llm_call_count:02d}",
            verdict_confirmed=(validation.verdict is Verdict.PASS or confirmed_defect),
            next_action_required=may_follow_up,
            create_regression_test=confirmed_defect,
            reason=opinion.reason,
            next_objective=opinion.next_objective if may_follow_up else None,
            follow_up_question=opinion.follow_up_question if may_follow_up else None,
            confidence=1.0,
        ),
        metadata,
    )
