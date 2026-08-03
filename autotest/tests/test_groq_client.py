"""Unit tests for bounded, Pydantic-validated Groq calls without network access."""

from __future__ import annotations

from types import SimpleNamespace

from myfinance_autotest import models
from myfinance_autotest.config import CampaignLimits, load_settings
from myfinance_autotest.state import CampaignState
from myfinance_autotest.tools.groq_client import GroqClient
from pydantic import BaseModel


class GeneratedAction(BaseModel):
    prompt: str


class BadRequestError(Exception):
    """Local stand-in whose name matches the Groq provider exception."""


class FakeCompletions:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = payloads
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.payloads.pop(0)
        if isinstance(content, Exception):
            raise content
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4),
        )


def _campaign() -> CampaignState:
    objective = models.TestObjective(
        objective_id="OBJ-1",
        category=models.TestCategory.REFORMULATION,
        description="Générer une reformulation sûre.",
        required_properties=["valid_json"],
        rationale="Le générateur doit retourner un objet validable.",
    )
    case = models.TestCase(
        test_id="TEST-1",
        title="Reformulation",
        category=models.TestCategory.REFORMULATION,
        channels=[models.Channel.API],
        input="Question financière",
        objective=objective,
        expected_properties=["valid_json"],
        failure_criteria=["invalid_json"],
    )
    return CampaignState.initialise(
        case,
        CampaignLimits(
            max_agent_steps=3,
            max_llm_calls_per_test=3,
            global_test_timeout_seconds=60,
            max_repeated_actions=2,
            min_evidence_confidence=0.8,
        ),
    )


def test_client_retries_invalid_json_then_returns_a_pydantic_object() -> None:
    completions = FakeCompletions(["not-json", '{"prompt":"PNB BIAT 2025"}'])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pauses: list[float] = []
    settings = load_settings(environment={"GROQ_API_KEY": "test-key"})
    client = GroqClient(settings, client_factory=lambda **_: fake_client, sleep=pauses.append)

    payload, result = client.complete_json(
        role="generator",
        system_prompt="Return JSON only.",
        user_prompt="Reformule la question.",
        response_model=GeneratedAction,
        campaign=_campaign(),
    )

    assert payload == GeneratedAction(prompt="PNB BIAT 2025")
    assert result.status == "success"
    assert result.attempts == 2
    assert pauses == [0.5]
    assert "response_format" not in completions.calls[0]
    assert completions.calls[0]["reasoning_effort"] == "low"


def test_client_stops_when_campaign_budget_is_exhausted() -> None:
    completions = FakeCompletions(['{"prompt":"first"}', '{"prompt":"second"}'])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = load_settings(environment={"GROQ_API_KEY": "test-key"})
    campaign = _campaign()
    campaign.limits.max_llm_calls_per_test = 1
    client = GroqClient(settings, client_factory=lambda **_: fake_client, sleep=lambda _: None)

    first, _ = client.complete_json(
        role="planner", system_prompt="JSON", user_prompt="one", response_model=GeneratedAction, campaign=campaign
    )
    second, result = client.complete_json(
        role="planner", system_prompt="JSON", user_prompt="two", response_model=GeneratedAction, campaign=campaign
    )

    assert first is not None
    assert second is None
    assert result.status == "failed"
    assert "budget" in (result.error or "")
    assert len(completions.calls) == 1


def test_client_does_not_retry_a_provider_bad_request() -> None:
    completions = FakeCompletions([BadRequestError("invalid request")])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pauses: list[float] = []
    settings = load_settings(environment={"GROQ_API_KEY": "test-key"})
    client = GroqClient(settings, client_factory=lambda **_: fake_client, sleep=pauses.append)

    payload, result = client.complete_json(
        role="generator", system_prompt="JSON", user_prompt="one", response_model=GeneratedAction, campaign=_campaign()
    )

    assert payload is None
    assert result.status == "failed"
    assert result.attempts == 1
    assert result.error == "Groq request failed: BadRequestError (invalid request)"
    assert len(completions.calls) == 1
    assert pauses == []


def test_client_accepts_a_json_object_wrapped_in_a_code_fence() -> None:
    completions = FakeCompletions(["```json\n{\"prompt\": \"PNB BIAT 2025\"}\n```"])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = load_settings(environment={"GROQ_API_KEY": "test-key"})
    client = GroqClient(settings, client_factory=lambda **_: fake_client, sleep=lambda _: None)

    payload, result = client.complete_json(
        role="generator", system_prompt="JSON", user_prompt="one", response_model=GeneratedAction, campaign=_campaign()
    )

    assert payload == GeneratedAction(prompt="PNB BIAT 2025")
    assert result.status == "success"
