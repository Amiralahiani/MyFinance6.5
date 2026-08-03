"""Evaluator/Critic tests prove that Groq cannot overturn deterministic evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from myfinance_autotest import models
from myfinance_autotest.agents.critic import critique_evaluation
from myfinance_autotest.agents.evaluator import evaluate_response
from myfinance_autotest.config import CampaignLimits, load_settings
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


def _case() -> models.TestCase:
    objective = models.TestObjective(
        objective_id="OBJ-EVAL-001",
        category=models.TestCategory.FINANCIAL_FACT,
        description="Évaluer une réponse financière après les contrôles de preuve.",
        required_properties=["source_fidelity"],
        rationale="La qualité ne doit pas remplacer la preuve PDF.",
    )
    return models.TestCase(
        test_id="TEST-EVAL-001",
        title="Évaluation PNB BIAT",
        category=models.TestCategory.FINANCIAL_FACT,
        channels=[models.Channel.API],
        input="Quel est le PNB de BIAT en 2025 ?",
        objective=objective,
        expected_properties=["source_fidelity"],
        failure_criteria=["wrong_year"],
    )


def _campaign(case: models.TestCase) -> CampaignState:
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


def _client(payloads: list[dict]) -> GroqClient:
    fake = SimpleNamespace(chat=SimpleNamespace(completions=_Completions(payloads)))
    return GroqClient(
        load_settings(environment={"GROQ_API_KEY": "test-key"}),
        client_factory=lambda **_: fake,
        sleep=lambda _: None,
    )


def _execution() -> models.ToolExecutionResult:
    timestamp = datetime.now(UTC)
    return models.ToolExecutionResult(
        action_id="ACTION-EVAL-001",
        channel=models.Channel.API,
        started_at=timestamp,
        finished_at=timestamp,
        latency_ms=10,
        http_status=200,
        response={"type": "numeric", "value": "123"},
    )


def _validation(verdict: models.Verdict) -> models.DeterministicValidationResult:
    failed = verdict is models.Verdict.FAIL
    return models.DeterministicValidationResult(
        test_id="TEST-EVAL-001",
        verdict=verdict,
        checks=[
            models.DeterministicCheck(
                check_id="year",
                name="reporting_year_matches_evidence",
                passed=not failed,
            )
        ],
        failure_categories=[models.FailureCategory.WRONG_YEAR] if failed else [],
    )


def _opinion(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "relevance": 5,
        "factuality": 5,
        "source_fidelity": 5,
        "conversation_coherence": 5,
        "year_respect": 5,
        "unit_respect": 5,
        "clarity": 5,
        "format_respect": 5,
        "failure_category": None,
        "probable_cause": None,
        "confidence": 0.9,
        "rationale": "La réponse est claire selon la revue qualitative.",
    }
    payload.update(overrides)
    return payload


def test_evaluator_cannot_turn_a_deterministic_fail_into_pass() -> None:
    case = _case()
    evaluation, _ = evaluate_response(
        case,
        _execution(),
        _validation(models.Verdict.FAIL),
        client=_client([_opinion()]),
        campaign=_campaign(case),
    )

    assert evaluation.verdict is models.Verdict.FAIL
    assert evaluation.failure_category is models.FailureCategory.WRONG_YEAR


def test_evaluator_can_warn_on_poor_clarity_after_a_technical_pass() -> None:
    case = _case()
    evaluation, _ = evaluate_response(
        case,
        _execution(),
        _validation(models.Verdict.PASS),
        client=_client([_opinion(clarity=2)]),
        campaign=_campaign(case),
    )

    assert evaluation.verdict is models.Verdict.WARNING


def test_critic_creates_a_regression_only_for_a_confirmed_business_defect() -> None:
    case = _case()
    campaign = _campaign(case)
    evaluation, _ = evaluate_response(
        case,
        _execution(),
        _validation(models.Verdict.FAIL),
        client=_client([_opinion()]),
        campaign=campaign,
    )
    critic, _ = critique_evaluation(
        case,
        evaluation,
        _validation(models.Verdict.FAIL),
        client=_client(
            [
                {
                    "next_action_required": True,
                    "reason": "Vérifier une autre formulation de la même demande.",
                    "next_objective": None,
                }
            ]
        ),
        campaign=campaign,
    )

    assert critic.verdict_confirmed
    assert critic.create_regression_test
    assert not critic.next_action_required
