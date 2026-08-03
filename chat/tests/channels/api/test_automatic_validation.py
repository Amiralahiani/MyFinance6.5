"""Tests of the deterministic gate between extraction and published facts."""

from __future__ import annotations

import json

from myfinance_agent_docs.catalog import PROJECT_ROOT
from myfinance_agent_docs.facts import auto_validated_fact
from myfinance_agent_docs.validation import validate_facts


def _biat_2025_fact(metric_id: str) -> dict:
    path = PROJECT_ROOT / "data" / "normalized" / "facts" / "auto_validated" / "biat" / "2025" / "financial_facts.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return next(item for item in payload if item["metric_id"] == metric_id)


def test_auto_validated_fact_is_the_only_fact_available_to_the_chat() -> None:
    fact = auto_validated_fact("biat", 2025, "net_banking_income")

    assert fact is not None
    assert fact.value == 1_594_799
    assert fact.validation_status == "auto_validated"


def test_gate_rejects_an_excerpt_that_does_not_exist_on_the_cited_page() -> None:
    invalid = _biat_2025_fact("net_banking_income")
    invalid["source_excerpt"] = "Cette preuve n'existe pas dans le PDF officiel."

    accepted, report = validate_facts([invalid])

    assert accepted == []
    assert report["rejected_fact_count"] == 1
    assert report["facts"][0]["checks"]["excerpt_found_on_source_page"] is False


def test_gate_rejects_duplicate_metric_for_the_same_document() -> None:
    fact = _biat_2025_fact("net_banking_income")

    accepted, report = validate_facts([fact, fact.copy()])

    assert accepted == []
    assert report["rejected_fact_count"] == 2
    assert all(not item["checks"]["unique_metric_per_document"] for item in report["facts"])


def test_metric_outside_the_common_catalog_is_not_published() -> None:
    invalid = _biat_2025_fact("net_banking_income")
    invalid["metric_id"] = "customer_loans_gross"
    invalid["fact_id"] = invalid["fact_id"].replace("net_banking_income", "customer_loans_gross")

    accepted, report = validate_facts([invalid])

    assert accepted == []
    assert report["facts"][0]["checks"]["metric_is_in_common_catalog"] is False
    assert auto_validated_fact("biat", 2025, "customer_loans_gross") is None
