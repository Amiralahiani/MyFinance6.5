"""Coverage reporting for the facts that the Chat is allowed to display."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from myfinance_contracts import SourceReference

from myfinance_agent_docs.catalog import load_catalog, load_common_extraction_profile
from myfinance_agent_docs.facts import AUTO_VALIDATED_FACTS_ROOT


def auto_validated_coverage(
    reports: Iterable[SourceReference] | None = None,
    *,
    metric_ids: Iterable[str] | None = None,
    facts_root: Path = AUTO_VALIDATED_FACTS_ROOT,
) -> dict[str, Any]:
    """Return an auditable matrix of present reports and display-safe facts.

    A missing cell is intentionally a coverage gap, not a value to infer.  The
    result is used by maintainers before extending a bank/year/metric scope and
    can be made strict by the caller once the target coverage is agreed.
    """

    selected_reports = sorted(reports if reports is not None else load_catalog(), key=lambda item: (item.bank_id, item.year))
    selected_metrics = tuple(metric_ids or load_common_extraction_profile()["metric_ids"])
    expected = len(selected_reports) * len(selected_metrics)
    validated = 0
    gaps: list[dict[str, Any]] = []
    for report in selected_reports:
        fact_path = facts_root / report.bank_id / str(report.year) / "financial_facts.json"
        accepted: set[str] = set()
        if fact_path.exists():
            payload = json.loads(fact_path.read_text(encoding="utf-8"))
            accepted = {
                str(item["metric_id"])
                for item in payload
                if item.get("validation_status") == "auto_validated"
            }
        present = [metric_id for metric_id in selected_metrics if metric_id in accepted]
        missing = [metric_id for metric_id in selected_metrics if metric_id not in accepted]
        validated += len(present)
        if missing:
            gaps.append(
                {
                    "bank_id": report.bank_id,
                    "bank_name": report.bank_name,
                    "reporting_year": report.year,
                    "missing_metric_ids": missing,
                }
            )
    return {
        "report_count": len(selected_reports),
        "core_metric_count": len(selected_metrics),
        "expected_fact_count": expected,
        "auto_validated_fact_count": validated,
        "coverage_percent": round((validated / expected * 100) if expected else 100, 1),
        "gaps": gaps,
    }
