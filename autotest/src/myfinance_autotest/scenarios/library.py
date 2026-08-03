"""Generate scenario coverage from official reports and auto-validated facts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from myfinance_agent_docs.catalog import (
    PROJECT_ROOT,
    bank_definitions,
    load_catalog,
    load_common_extraction_profile,
)
from myfinance_agent_docs.facts import AUTO_VALIDATED_FACTS_ROOT
from pydantic import BaseModel, Field

from myfinance_autotest.models import Channel, TestCase, TestCategory, TestObjective

_QUESTION_LABELS = {
    "total_assets": "total des actifs",
    "total_liabilities": "total des passifs",
    "total_equity": "total des capitaux propres",
    "net_income": "résultat net",
    "customer_loans_net": "créances sur la clientèle",
    "customer_deposits": "dépôts de la clientèle",
    "net_banking_income": "PNB",
}
_PREFERRED_CROSS_METRICS = ("net_banking_income", "net_income", "total_assets")


class ReportScenarioCoverage(BaseModel):
    bank_id: str
    reporting_year: int
    source_path: str
    auto_validated_metrics: list[str] = Field(default_factory=list)
    missing_core_metrics: list[str] = Field(default_factory=list)
    api_scenario_count: int = Field(ge=0)
    cross_channel_scenario_id: str | None = None


class ScenarioLibrary(BaseModel):
    version: str = "1.0"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    report_count: int = Field(ge=0)
    auto_validated_fact_scenario_count: int = Field(ge=0)
    cross_channel_scenario_count: int = Field(ge=0)
    missing_fact_scenario_count: int = Field(ge=0)
    behavior_scenario_count: int = Field(default=0, ge=0)
    coverage: list[ReportScenarioCoverage]
    scenarios: list[TestCase]


def _question(bank_id: str, year: int, metric_id: str) -> str:
    bank_name = bank_definitions()[bank_id][0]
    label = _QUESTION_LABELS.get(metric_id, metric_id.replace("_", " "))
    if metric_id in {"customer_deposits", "customer_loans_net", "total_assets", "total_liabilities", "total_equity"}:
        return f"Quels sont les {label} de {bank_name} en {year} ?"
    return f"Quel est le {label} de {bank_name} en {year} ?"


def _objective(identifier: str, category: TestCategory, description: str, properties: list[str]) -> TestObjective:
    return TestObjective(
        objective_id=identifier,
        category=category,
        description=description,
        required_properties=properties,
        rationale="Scénario produit depuis le fait auto-validé ou le catalogue officiel, jamais depuis une valeur attendue écrite à la main.",
    )


def _fact_scenario(bank_id: str, year: int, metric_id: str) -> TestCase:
    scenario_id = f"FACT-{bank_id.upper()}-{year}-{metric_id.upper()}"
    return TestCase(
        test_id=scenario_id,
        title=f"{_QUESTION_LABELS.get(metric_id, metric_id.replace('_', ' '))} · {bank_definitions()[bank_id][0]} · {year}",
        category=TestCategory.FINANCIAL_FACT,
        channels=[Channel.API],
        input=_question(bank_id, year, metric_id),
        objective=_objective(
            f"OBJ-{scenario_id}",
            TestCategory.FINANCIAL_FACT,
            "Vérifier une valeur avec son fait auto-validé et sa preuve PDF.",
            ["numeric_value", "reporting_year", "unit", "source_document", "source_page", "source_excerpt"],
        ),
        bank_id=bank_id,
        reporting_year=year,
        metric_id=metric_id,
        expected_properties=["numeric_value", "reporting_year", "unit", "source_document", "source_page", "source_excerpt"],
        failure_criteria=["unsupported_value", "wrong_year", "wrong_unit", "source_mismatch"],
        origin="catalog_auto_validated_fact",
    )


def _cross_scenario(bank_id: str, year: int, metric_id: str) -> TestCase:
    scenario_id = f"CROSS-{bank_id.upper()}-{year}-{metric_id.upper()}"
    return TestCase(
        test_id=scenario_id,
        title=f"API ↔ Web · {_QUESTION_LABELS.get(metric_id, metric_id.replace('_', ' '))} · {bank_definitions()[bank_id][0]} · {year}",
        category=TestCategory.CROSS_CHANNEL,
        channels=[Channel.API, Channel.WEB],
        input=_question(bank_id, year, metric_id),
        objective=_objective(
            f"OBJ-{scenario_id}",
            TestCategory.CROSS_CHANNEL,
            "Comparer le chiffre et la preuve PDF visibles sur l’API et le Web.",
            ["same_type", "same_value", "same_year", "same_source"],
        ),
        bank_id=bank_id,
        reporting_year=year,
        metric_id=metric_id,
        expected_properties=["same_type", "same_value", "same_year", "same_source"],
        failure_criteria=["channel_divergence", "frontend_error", "api_error"],
        origin="catalog_report_cross_channel",
    )


def _missing_fact_scenario(bank_id: str, year: int, metric_id: str) -> TestCase:
    scenario_id = f"MISSING-{bank_id.upper()}-{year}-{metric_id.upper()}"
    return TestCase(
        test_id=scenario_id,
        title=f"Absence de fait validé · {metric_id} · {bank_definitions()[bank_id][0]} · {year}",
        category=TestCategory.FINANCIAL_FACT,
        channels=[Channel.API],
        input=_question(bank_id, year, metric_id),
        objective=_objective(
            f"OBJ-{scenario_id}",
            TestCategory.FINANCIAL_FACT,
            "Vérifier que l’API s’abstient lorsqu’aucun fait auto-validé n’est disponible.",
            ["no_invented_value", "explicit_validation_gap"],
        ),
        bank_id=bank_id,
        reporting_year=year,
        metric_id=metric_id,
        expected_properties=["no_invented_value", "explicit_validation_gap"],
        failure_criteria=["unsupported_value"],
        origin="catalog_missing_auto_validated_fact",
    )


def _behavior_scenario(
    scenario_id: str,
    title: str,
    question: str,
    *,
    category: TestCategory,
    channels: list[Channel],
    expected_properties: list[str],
    bank_id: str | None = None,
    year: int | None = None,
    metric_id: str | None = None,
    context: dict | None = None,
) -> TestCase:
    return TestCase(
        test_id=scenario_id,
        title=title,
        category=category,
        channels=channels,
        input=question,
        objective=_objective(
            f"OBJ-{scenario_id}", category,
            "Vérifier un comportement observable du parcours sans imposer une valeur financière inventée.",
            expected_properties,
        ),
        bank_id=bank_id,
        reporting_year=year,
        metric_id=metric_id,
        conversation_context=context or {},
        expected_properties=expected_properties,
        failure_criteria=["contract_mismatch", "api_error", "frontend_error"],
        origin="catalog_behavior_contract",
    )


def _load_report_facts(bank_id: str, year: int) -> list[dict[str, object]]:
    path = AUTO_VALIDATED_FACTS_ROOT / bank_id / str(year) / "financial_facts.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in payload if item.get("validation_status") == "auto_validated"]


def build_scenario_library() -> ScenarioLibrary:
    """Cover every official report, every safe fact and every known validation gap."""

    core_metrics = list(load_common_extraction_profile()["metric_ids"])
    coverage: list[ReportScenarioCoverage] = []
    scenarios: list[TestCase] = []
    fact_count = 0
    cross_count = 0
    missing_count = 0
    for report in load_catalog():
        facts = _load_report_facts(report.bank_id, report.year)
        metric_ids = sorted(str(item["metric_id"]) for item in facts)
        for metric_id in metric_ids:
            scenarios.append(_fact_scenario(report.bank_id, report.year, metric_id))
            fact_count += 1
        missing = sorted(set(core_metrics) - set(metric_ids))
        for metric_id in missing:
            scenarios.append(_missing_fact_scenario(report.bank_id, report.year, metric_id))
            missing_count += 1
        cross_metric = next((item for item in _PREFERRED_CROSS_METRICS if item in metric_ids), None)
        cross_scenario_id = None
        if cross_metric is not None:
            cross = _cross_scenario(report.bank_id, report.year, cross_metric)
            scenarios.append(cross)
            cross_count += 1
            cross_scenario_id = cross.test_id
        coverage.append(
            ReportScenarioCoverage(
                bank_id=report.bank_id,
                reporting_year=report.year,
                source_path=report.path,
                auto_validated_metrics=metric_ids,
                missing_core_metrics=missing,
                api_scenario_count=len(metric_ids) + len(missing),
                cross_channel_scenario_id=cross_scenario_id,
            )
        )
    behavior_scenarios = [
        _behavior_scenario(
            "BEHAVIOR-MISSING-YEAR", "Précision d’année requise", "Quel est le PNB de BIAT ?",
            category=TestCategory.CONVERSATION, channels=[Channel.API],
            expected_properties=["response_type:clarification", "no_numeric_value", "message_contains:année"],
            bank_id="biat",
        ),
        _behavior_scenario(
            "BEHAVIOR-UNKNOWN-METRIC", "Refus d’une métrique inconnue", "Quel est le bitcoin de BIAT en 2025 ?",
            category=TestCategory.CONVERSATION, channels=[Channel.API],
            expected_properties=["response_type:clarification", "no_numeric_value", "message_contains:indicateur financier"],
            bank_id="biat", year=2025,
        ),
        _behavior_scenario(
            "BEHAVIOR-DOCUMENT", "Réponse documentaire sourcée", "Explique le portefeuille d'encaissement de BIAT en 2021",
            category=TestCategory.SOURCE, channels=[Channel.API],
            expected_properties=["response_type:document", "evidence_present"], bank_id="biat", year=2021,
        ),
        _behavior_scenario(
            "BEHAVIOR-CONTEXT", "Relance avec contexte confirmé", "Et en 2024 ?",
            category=TestCategory.FINANCIAL_FACT, channels=[Channel.API],
            expected_properties=["numeric_value", "reporting_year", "unit", "source_document", "source_page", "source_excerpt"],
            bank_id="biat", year=2024, metric_id="net_banking_income",
            context={"mode": "metric", "bank_id": "biat", "bank_name": "BIAT", "reporting_year": 2025, "metric_id": "net_banking_income"},
        ),
        _behavior_scenario(
            "BEHAVIOR-WEB-GREETING", "Accueil dans l’interface Web", "Bonjour",
            category=TestCategory.CONVERSATION, channels=[Channel.WEB],
            expected_properties=["response_type:courtesy", "visible_contains:prêt à analyser"],
        ),
    ]
    scenarios.extend(behavior_scenarios)
    return ScenarioLibrary(
        report_count=len(coverage),
        auto_validated_fact_scenario_count=fact_count,
        cross_channel_scenario_count=cross_count,
        missing_fact_scenario_count=missing_count,
        behavior_scenario_count=len(behavior_scenarios),
        coverage=coverage,
        scenarios=scenarios,
    )


def write_scenario_library(library: ScenarioLibrary, root: Path = PROJECT_ROOT / "data" / "autotest" / "scenarios") -> Path:
    """Persist the generated catalogue atomically for a reproducible campaign."""

    root.mkdir(parents=True, exist_ok=True)
    path = root / "scenario_library.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(library.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path
