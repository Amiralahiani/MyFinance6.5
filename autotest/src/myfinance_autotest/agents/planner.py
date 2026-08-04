"""Groq-backed action selection constrained by a local executor policy."""

from __future__ import annotations

import json

from myfinance_autotest.models import ActionKind, Channel, PlannedAction, PlannerRationale, TestCase
from myfinance_autotest.state import CampaignState
from myfinance_autotest.tools.groq_client import GroqCallResult, GroqClient

_SYSTEM_PROMPT = """You review one safe test action for a supplied English question.
Return only {"rationale": "..."}. The local application, not you, creates the
action, channel, question and parameters. Keep the rationale under one sentence.
Do not propose commands, URLs, selectors, credentials, files or databases."""


def plan_api_action(
    test_case: TestCase,
    *,
    client: GroqClient,
    campaign: CampaignState,
) -> tuple[PlannedAction | None, GroqCallResult]:
    """Obtain one action, accepting only the API conversation action supported now."""

    proposal, metadata = client.complete_json(
        role="planner",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=json.dumps(
            {
                "question": test_case.input,
                "local_policy": "The only executable action is send_message to the local Chat API.",
            },
            ensure_ascii=False,
        ),
        response_model=PlannerRationale,
        campaign=campaign,
        max_completion_tokens=160,
    )
    rationale = proposal.rationale if proposal is not None else "Local fallback plan: send the validated question to the local API."
    if proposal is None:
        metadata = metadata.model_copy(
            update={
                "status": "fallback_local",
                "error": metadata.error or "The AI Planner is unavailable; local policy authorises this bounded action.",
            }
        )
    # Every execution-relevant field is assigned locally, whether the Planner
    # returned a rationale or the bounded fallback was used.
    return (
        PlannedAction(
            action_id=f"{test_case.test_id}-ACTION-{campaign.llm_call_count:02d}",
            objective_id=test_case.objective.objective_id,
            kind=ActionKind.SEND_MESSAGE,
            channel=Channel.API,
            rationale=rationale,
            question=test_case.input,
            parameters={"context": test_case.conversation_context},
        ),
        metadata,
    )
