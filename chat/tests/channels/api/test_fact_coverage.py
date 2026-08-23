import json

from myfinance_agent_docs.coverage import auto_validated_coverage
from myfinance_contracts import SourceReference


def test_coverage_reports_only_missing_display_safe_facts(tmp_path) -> None:
    reports = [
        SourceReference(bank_id="biat", bank_name="BIAT", year=2023, path="biat.pdf"),
        SourceReference(bank_id="bt", bank_name="Banque de Tunisie", year=2023, path="bt.pdf"),
    ]
    fact_path = tmp_path / "biat" / "2023" / "financial_facts.json"
    fact_path.parent.mkdir(parents=True)
    fact_path.write_text(
        json.dumps(
            [
                {"metric_id": "net_income", "validation_status": "auto_validated"},
                {"metric_id": "net_banking_income", "validation_status": "candidate"},
            ]
        ),
        encoding="utf-8",
    )

    coverage = auto_validated_coverage(
        reports,
        metric_ids=["net_income", "net_banking_income"],
        facts_root=tmp_path,
    )

    assert coverage["expected_fact_count"] == 4
    assert coverage["auto_validated_fact_count"] == 1
    assert coverage["coverage_percent"] == 25.0
    assert coverage["gaps"] == [
        {
            "bank_id": "biat",
            "bank_name": "BIAT",
            "reporting_year": 2023,
            "missing_metric_ids": ["net_banking_income"],
        },
        {
            "bank_id": "bt",
            "bank_name": "Banque de Tunisie",
            "reporting_year": 2023,
            "missing_metric_ids": ["net_income", "net_banking_income"],
        },
    ]
