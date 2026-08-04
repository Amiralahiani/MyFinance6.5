"""The batch runner applies source validation and expected-absence rules."""

from datetime import UTC, datetime

from myfinance_agent_docs.facts import auto_validated_fact
from myfinance_autotest import models
from myfinance_autotest.campaign_runner import run_scenario_batch, write_campaign_report
from myfinance_autotest.scenarios.library import ScenarioLibrary


class _Api:
    def execute(self, action):
        now = datetime.now(UTC)
        if action.parameters == {"context": {}} and "Zitouna" in action.question:
            response = {
                "type": "clarification",
                "message": "Cette métrique n’a pas encore passé la validation automatique pour ce rapport ; aucune valeur n’est inventée.",
            }
        else:
            fact = auto_validated_fact("biat", 2025, "net_banking_income")
            assert fact is not None
            response = {
                "type": "numeric", "metric_id": fact.metric_id, "value": str(fact.value), "currency": fact.currency,
                "unit_scale": fact.unit_scale, "reporting_year": fact.reporting_year,
                "source_document": fact.source_path, "page_number": fact.page_number,
                "source_excerpt": fact.source_excerpt,
            }
        return models.ToolExecutionResult(
            action_id=action.action_id, channel=models.Channel.API, started_at=now, finished_at=now,
            latency_ms=1, http_status=200, response=response,
        )


def _case(origin: str, bank_id: str, year: int, metric_id: str) -> models.TestCase:
    objective = models.TestObjective(
        objective_id=f"OBJ-{origin}", category=models.TestCategory.FINANCIAL_FACT,
        description="Vérifier un scénario de campagne.", required_properties=["source"], rationale="Test.",
    )
    return models.TestCase(
        test_id=f"TEST-{origin}", title=origin, category=models.TestCategory.FINANCIAL_FACT,
        channels=[models.Channel.API], input=("Quel est le résultat net de Banque Zitouna en 2021 ?" if bank_id == "zitouna" else "Quel est le PNB de BIAT en 2025 ?"),
        objective=objective, bank_id=bank_id, reporting_year=year, metric_id=metric_id,
        expected_properties=["source"], failure_criteria=["unsupported_value"], origin=origin,
    )


def test_campaign_runner_passes_a_fact_and_an_expected_absence(tmp_path) -> None:
    library = ScenarioLibrary(
        report_count=2, auto_validated_fact_scenario_count=1, cross_channel_scenario_count=0,
        missing_fact_scenario_count=1, coverage=[],
        scenarios=[
            _case("catalog_auto_validated_fact", "biat", 2025, "net_banking_income"),
            _case("catalog_missing_auto_validated_fact", "zitouna", 2021, "net_income"),
        ],
    )
    report = run_scenario_batch(library, api_executor=_Api())

    assert [item.verdict for item in report.tests] == [models.Verdict.PASS, models.Verdict.PASS]
    paths = write_campaign_report(report, tmp_path)
    assert all(path.exists() for path in paths)
    summary_markdown = next(path for path in paths if path.name == "summary.md").read_text(encoding="utf-8")
    audit_markdown = next(path for path in paths if path.name == "audit.md").read_text(encoding="utf-8")
    assert "## Quick decision" in summary_markdown
    assert "## TEST-catalog_auto_validated_fact" in audit_markdown


def test_runner_publishes_the_chat_response_before_quality_evaluation() -> None:
    library = ScenarioLibrary(
        report_count=1, auto_validated_fact_scenario_count=1, cross_channel_scenario_count=0,
        missing_fact_scenario_count=0, coverage=[],
        scenarios=[_case("catalog_auto_validated_fact", "biat", 2025, "net_banking_income")],
    )
    executions: list[tuple[int, int, str]] = []

    report = run_scenario_batch(
        library,
        api_executor=_Api(),
        on_execution_complete=lambda index, total, scenario, _: executions.append((index, total, scenario.test_id)),
    )

    assert executions == [(1, 1, "TEST-catalog_auto_validated_fact")]
    assert len(report.tests) == 1


def test_exploration_contract_fails_when_chat_returns_a_number_instead_of_clarifying() -> None:
    objective = models.TestObjective(
        objective_id="OBJ-EXPLORATION-UNIT",
        category=models.TestCategory.CONVERSATION,
        description="Refuser une devise non vérifiée.",
        required_properties=["response_type:clarification", "no_numeric_value"],
        rationale="Une conversion sans taux de change sourcé ne doit pas produire de chiffre.",
    )
    scenario = models.TestCase(
        test_id="EXPLORE-UNIT-TRAP",
        title="Conversion non vérifiée",
        category=models.TestCategory.CONVERSATION,
        channels=[models.Channel.API],
        input="Donne le résultat net de BIAT en dollars.",
        objective=objective,
        expected_properties=["response_type:clarification", "no_numeric_value"],
        failure_criteria=["hallucination"],
        origin="groq_exploration_generator",
    )
    library = ScenarioLibrary(
        report_count=0, auto_validated_fact_scenario_count=0, cross_channel_scenario_count=0,
        missing_fact_scenario_count=0, coverage=[], scenarios=[scenario],
    )

    report = run_scenario_batch(library, api_executor=_Api())

    assert report.tests[0].verdict is models.Verdict.FAIL
