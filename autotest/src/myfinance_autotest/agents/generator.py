"""Groq-backed generation of bounded, schema-validated test cases."""

from __future__ import annotations

import json

from myfinance_autotest.models import Channel, GeneratedQuestion, TestCase
from myfinance_autotest.state import CampaignState
from myfinance_autotest.tools.groq_client import GroqCallResult, GroqClient

_SYSTEM_PROMPT = """You generate one natural French question for an autonomous banking-chat test.
The supplied seed is a risk charter, not a test to copy. Produce one new,
natural French user question that probes exactly the stated risk and its required
behaviour: hallucination, missing information, contradictory context, unsupported
request, source traceability or reformulation. A generic financial-value question
is invalid unless it tests the charter's stated risk. Return only the JSON object
{"title": "...", "question": "..."}.
Never provide an expected financial number, source, tool instruction, credential,
filesystem access, database access or network endpoint. Preserve the bank, year
and metric when they are present in the seed. Keep the title and question concise."""


def generate_test_case(
    seed: TestCase,
    *,
    allowed_channels: set[Channel],
    client: GroqClient,
    campaign: CampaignState,
    excluded_questions: list[str] | None = None,
) -> tuple[GeneratedQuestion | None, GroqCallResult]:
    """Ask Groq for wording only; executable rules remain entirely local."""

    generated, metadata = client.complete_json(
        role="generator",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=json.dumps(
            {
                "risk_charter": {
                    "title": seed.title,
                    "example_question": seed.input,
                    "risk_description": seed.objective.description,
                    "required_properties": seed.expected_properties,
                    "failure_criteria": seed.failure_criteria,
                    "bank_id": seed.bank_id,
                    "reporting_year": seed.reporting_year,
                    "metric_id": seed.metric_id,
                },
                "allowed_channels": sorted(channel.value for channel in allowed_channels),
                # Local similarity checks cover the full history. Sending only
                # recent examples keeps the provider prompt bounded and avoids
                # spending most of the daily quota on old questions.
                "excluded_questions": (excluded_questions or [])[-16:],
                "instruction": (
                    "Generate exactly one new question that tests the supplied risk charter. "
                    "Do not copy the example wording and do not repeat or closely paraphrase "
                    "an excluded question. Do not replace the stated risk with a generic request."
                ),
            },
            ensure_ascii=False,
        ),
        response_model=GeneratedQuestion,
        campaign=campaign,
        max_completion_tokens=260,
    )
    if generated is None:
        return None, metadata
    return generated, metadata
