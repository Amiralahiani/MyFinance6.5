"""Show one real Groq-generated test case and one policy-checked API action."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "shared" / "contracts" / "src"),
    str(ROOT / "chat" / "knowledge" / "src"),
    str(ROOT / "chat" / "api" / "src"),
]

from myfinance_autotest import models
from myfinance_autotest.agents.generator import generate_test_case
from myfinance_autotest.agents.planner import plan_api_action
from myfinance_autotest.config import load_settings
from myfinance_autotest.scenarios.exploration import bind_generated_scenario
from myfinance_autotest.state import CampaignState
from myfinance_autotest.tools.groq_client import GroqClient


def _seed() -> models.TestCase:
    objective = models.TestObjective(
        objective_id="OBJ-GROQ-DEMO-001",
        category=models.TestCategory.FINANCIAL_FACT,
        description="Créer un scénario API financier vérifiable par une preuve PDF.",
        required_properties=["source_fidelity", "year_respect"],
        rationale="La démonstration doit rester contrôlable par le validateur déterministe.",
    )
    return models.TestCase(
        test_id="TEST-GROQ-DEMO-001",
        title="PNB BIAT 2025",
        category=models.TestCategory.FINANCIAL_FACT,
        channels=[models.Channel.API],
        input="Quel est le PNB de BIAT en 2025 ?",
        objective=objective,
        bank_id="biat",
        reporting_year=2025,
        metric_id="net_banking_income",
        expected_properties=["source_fidelity", "year_respect"],
        failure_criteria=["unsupported_value", "wrong_year", "source_mismatch"],
        origin="demo_seed",
    )


def main() -> None:
    settings = load_settings()
    settings.require_groq_api_key()
    seed = _seed()
    campaign = CampaignState.initialise(seed, settings.limits)
    client = GroqClient(settings)

    generated, generation = generate_test_case(
        seed,
        allowed_channels={models.Channel.API},
        client=client,
        campaign=campaign,
    )
    if generated is None:
        raise SystemExit(f"Génération refusée ou indisponible : {generation.error or generation.status}")
    scenario = bind_generated_scenario(seed, generated, 1)
    action, planning = plan_api_action(scenario, client=client, campaign=campaign)
    if action is None:
        raise SystemExit(f"Planification refusée ou indisponible : {planning.error or planning.status}")

    print("SCÉNARIO GÉNÉRÉ (Groq, validé par Pydantic et la politique locale)")
    print(scenario.model_dump_json(indent=2))
    print("\nACTION PLANIFIÉE (Groq, contrôlée avant exécution)")
    print(action.model_dump_json(indent=2))
    print(f"\nAppels Groq : {campaign.llm_call_count}/{settings.limits.max_llm_calls_per_test}")


if __name__ == "__main__":
    main()
