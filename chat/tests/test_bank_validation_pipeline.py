"""Integration evidence for the five-bank automatic validation pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "shared" / "contracts" / "src"), str(ROOT / "chat" / "knowledge" / "src")]

from myfinance_agent_docs.catalog import load_catalog, load_common_extraction_profile


def test_catalogue_defines_a_common_core_for_all_five_banks() -> None:
    profile = load_common_extraction_profile()

    assert set(profile["metric_ids"]) == {
        "total_assets",
        "total_liabilities",
        "total_equity",
        "net_income",
        "customer_loans_net",
        "customer_deposits",
        "net_banking_income",
    }
    assert set(profile["statement_label_aliases"]) == set(profile["metric_ids"])
    assert len(load_catalog()) == 25


def test_every_catalogued_report_has_a_successful_automatic_validation_run() -> None:
    expected_metrics = set(load_common_extraction_profile()["metric_ids"])
    reports = load_catalog()

    missing: list[tuple[str, int, set[str]]] = []
    for source in reports:
        report_path = ROOT / "data" / "validation-runs" / source.bank_id / str(source.year) / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))

        assert report["validation_engine"] == "deterministic-v2"
        assert report["rejected_fact_count"] == 0
        found = {fact["metric_id"] for fact in report["facts"]}
        assert found <= expected_metrics
        assert all(fact["status"] == "auto_validated" for fact in report["facts"])
        missing.append((source.bank_id, source.year, expected_metrics - found))

    # Banque Zitouna 2021 has an explicitly scoped source profile: its clean
    # equity-statement line is used because the income-statement OCR spaces every
    # digit. The PDF page, unit and individual scope still pass validation.
    assert missing == [
        ("amen_bank", 2021, set()),
        ("amen_bank", 2022, set()),
        ("amen_bank", 2023, set()),
        ("amen_bank", 2024, set()),
        ("amen_bank", 2025, set()),
        ("attijari_bank", 2021, set()),
        ("attijari_bank", 2022, set()),
        ("attijari_bank", 2023, set()),
        ("attijari_bank", 2024, set()),
        ("attijari_bank", 2025, set()),
        ("biat", 2021, set()),
        ("biat", 2022, set()),
        ("biat", 2023, set()),
        ("biat", 2024, set()),
        ("biat", 2025, set()),
        ("bt", 2021, set()),
        ("bt", 2022, set()),
        ("bt", 2023, set()),
        ("bt", 2024, set()),
        ("bt", 2025, set()),
        ("zitouna", 2021, set()),
        ("zitouna", 2022, set()),
        ("zitouna", 2023, set()),
        ("zitouna", 2024, set()),
        ("zitouna", 2025, set()),
    ]
