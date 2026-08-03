"""Deterministic catalogue of official reports present in the local project."""

from __future__ import annotations

import json
import re
from pathlib import Path

from myfinance_contracts import SourceReference

PROJECT_ROOT = Path(__file__).resolve().parents[4]
REPORTS_ROOT = PROJECT_ROOT / "data" / "raw" / "official-reports" / "etat financier"
METRICS_CATALOG_PATH = PROJECT_ROOT / "data" / "reference" / "financial_metrics.json"

_BANKS: dict[str, tuple[str, tuple[str, ...]]] = {
    "amen_bank": ("Amen Bank", ("amen bank", "amen")),
    "attijari_bank": ("Attijari Bank", ("attijari bank", "attijari")),
    "biat": ("BIAT", ("biat",)),
    "bt": ("Banque de Tunisie", ("banque de tunisie", "bt")),
    "zitouna": ("Banque Zitouna", ("banque zitouna", "zitouna")),
}


def bank_definitions() -> dict[str, tuple[str, tuple[str, ...]]]:
    """Expose supported banks and their user-facing aliases."""
    return _BANKS


def load_metric_catalog() -> list[dict[str, object]]:
    """Load the versioned business definitions of supported financial metrics."""
    payload = json.loads(METRICS_CATALOG_PATH.read_text(encoding="utf-8"))
    return payload["metrics"]


def load_common_extraction_profile() -> dict[str, object]:
    """Load the bank-neutral core metrics and their accepted statement labels."""
    payload = json.loads(METRICS_CATALOG_PATH.read_text(encoding="utf-8"))
    return payload["common_extraction_profile"]


def assessment_metrics() -> dict[str, tuple[str, ...]]:
    """Expose every approved reported metric for user intent detection."""
    return {
        str(metric["metric_id"]): tuple(str(alias) for alias in metric["query_aliases"])
        for metric in load_metric_catalog()
        if metric["lifecycle_status"] == "approved_for_design"
        and metric["metric_type"] == "reported"
    }


def _report_year(path: Path) -> int | None:
    full_year = re.search(r"(?<!\d)(20(?:2[1-5]))(?!\d)", path.stem)
    if full_year:
        return int(full_year.group(1))
    short_year = re.search(r"(2[1-5])$", path.stem)
    return 2000 + int(short_year.group(1)) if short_year else None


def load_catalog(root: Path = REPORTS_ROOT) -> list[SourceReference]:
    """List only report files whose bank and year can be identified safely."""
    reports: list[SourceReference] = []
    for bank_id, (bank_name, _) in _BANKS.items():
        bank_dir = root / bank_id
        if not bank_dir.exists():
            continue
        for path in sorted(bank_dir.glob("*.pdf")):
            year = _report_year(path)
            if year is None:
                continue
            reports.append(
                SourceReference(
                    bank_id=bank_id,
                    bank_name=bank_name,
                    year=year,
                    path=path.relative_to(PROJECT_ROOT).as_posix(),
                )
            )
    return sorted(reports, key=lambda report: (report.bank_id, report.year))


def reports_for(bank_ids: list[str], years: list[int]) -> list[SourceReference]:
    """Return exact local reports for the requested bank/year combinations."""
    wanted = {(bank_id, year) for bank_id in bank_ids for year in years}
    return [report for report in load_catalog() if (report.bank_id, report.year) in wanted]
