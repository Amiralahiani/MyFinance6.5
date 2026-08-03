from myfinance_autotest import models
from myfinance_autotest.scenarios.exploration import bind_generated_scenario, exploration_charters


def test_exploration_charters_define_risk_contracts_without_executable_catalog_cases() -> None:
    charters = exploration_charters()

    assert len(charters) == 12
    assert all(item.origin == "exploration_charter" for item in charters)
    assert all(item.expected_properties for item in charters)
    assert any("no_numeric_value" in item.expected_properties for item in charters)


def test_binding_keeps_ai_wording_but_local_safety_contract() -> None:
    charter = exploration_charters()[0]
    model_output = models.GeneratedQuestion(
        title="Question ambiguë produite par IA",
        question="Peux-tu me donner le PNB récent de BIAT ?",
    )

    scenario = bind_generated_scenario(charter, model_output, 1)

    assert scenario.origin == "groq_exploration_generator"
    assert scenario.input == "Peux-tu me donner le PNB récent de BIAT ?"
    assert scenario.expected_properties == charter.expected_properties
    assert scenario.objective == charter.objective
