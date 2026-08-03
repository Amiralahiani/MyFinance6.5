"""Generator/Planner tests use fake Groq completions: no key or network needed."""

from __future__ import annotations

import json
from types import SimpleNamespace

from myfinance_autotest import models
from myfinance_autotest.agents.generator import generate_test_case
from myfinance_autotest.agents.planner import plan_api_action
from myfinance_autotest.config import CampaignLimits, load_settings
from myfinance_autotest.scenarios.exploration import bind_generated_scenario
from myfinance_autotest.state import CampaignState
from myfinance_autotest.tools.groq_client import GroqClient


class _Completions:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = [json.dumps(payload) for payload in payloads]

    def create(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.payloads.pop(0)))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


def _seed() -> models.TestCase:
    objective = models.TestObjective(
        objective_id="OBJ-GEN-001",
        category=models.TestCategory.FINANCIAL_FACT,
        description="Tester une question PNB sourcée.",
        required_properties=["source_fidelity"],
        rationale="Le scénario doit pouvoir être vérifié par une preuve PDF.",
    )
    return models.TestCase(
        test_id="TEST-GEN-001",
        title="PNB BIAT 2025",
        category=models.TestCategory.FINANCIAL_FACT,
        channels=[models.Channel.API],
        input="Quel est le PNB de BIAT en 2025 ?",
        objective=objective,
        bank_id="biat",
        reporting_year=2025,
        metric_id="net_banking_income",
        expected_properties=["source_fidelity"],
        failure_criteria=["unsupported_value"],
    )


def _campaign(seed: models.TestCase) -> CampaignState:
    return CampaignState.initialise(
        seed,
        CampaignLimits(
            max_agent_steps=3,
            max_llm_calls_per_test=3,
            global_test_timeout_seconds=60,
            max_repeated_actions=2,
            min_evidence_confidence=0.8,
        ),
    )


def _client(payloads: list[dict]) -> GroqClient:
    completions = _Completions(payloads)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return GroqClient(
        load_settings(environment={"GROQ_API_KEY": "test-key"}),
        client_factory=lambda **_: fake_client,
        sleep=lambda _: None,
    )


def test_generator_accepts_a_small_question_payload() -> None:
    seed = _seed()
    generated, metadata = generate_test_case(
        seed,
        allowed_channels={models.Channel.API},
        client=_client([{"title": "PNB sans exercice", "question": "Quel est le PNB de BIAT ?"}]),
        campaign=_campaign(seed),
    )

    assert metadata.status == "success"
    assert generated is not None
    assert generated.title == "PNB sans exercice"
    assert generated.question == "Quel est le PNB de BIAT ?"


def test_local_charter_binds_all_execution_rules_to_generated_wording() -> None:
    seed = _seed()
    generated = models.GeneratedQuestion(
        title="PNB sans exercice",
        question="Quel est le PNB de BIAT ?",
    )
    scenario = bind_generated_scenario(seed, generated, 1)

    assert scenario.test_id == "EXPLORE-001-TEST-GEN-001"
    assert scenario.input == generated.question
    assert scenario.channels == [models.Channel.API]
    assert scenario.expected_properties == seed.expected_properties
    assert scenario.origin == "groq_exploration_generator"


def test_planner_allows_only_the_local_api_send_message_action() -> None:
    seed = _seed()
    proposal = {"rationale": "La question est envoyée à l’API locale du Chat."}
    campaign = _campaign(seed)
    action, metadata = plan_api_action(seed, client=_client([proposal]), campaign=campaign)

    assert metadata.status == "success"
    assert action is not None
    assert action.action_id == "TEST-GEN-001-ACTION-01"
    assert action.objective_id == seed.objective.objective_id
    assert action.parameters == {"context": {}}


def test_planner_ignores_untrusted_action_fields_and_uses_local_policy() -> None:
    seed = _seed()
    proposal = {
        "rationale": "Ouvrir une page externe.",
        "question": seed.input,
        "url": "https://example.invalid",
    }

    action, metadata = plan_api_action(seed, client=_client([proposal]), campaign=_campaign(seed))

    assert action is not None
    assert metadata.status == "success"
    assert action.kind is models.ActionKind.SEND_MESSAGE
    assert action.channel is models.Channel.API
    assert action.url is None


def test_planner_uses_the_bounded_local_action_when_its_rationale_is_invalid() -> None:
    seed = _seed()
    action, metadata = plan_api_action(seed, client=_client([{}, {}, {}]), campaign=_campaign(seed))

    assert action is not None
    assert metadata.status == "fallback_local"
    assert action.question == seed.input
    assert action.parameters == {"context": {}}
