"""Deterministic validation gate between PDF extraction and answerable facts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from myfinance_contracts import FinancialFact
from pydantic import ValidationError

from myfinance_agent_docs.catalog import PROJECT_ROOT, load_common_extraction_profile

AUTO_VALIDATED_ROOT = PROJECT_ROOT / "data" / "normalized" / "facts" / "auto_validated"
VALIDATION_RUNS_ROOT = PROJECT_ROOT / "data" / "validation-runs"

_METRIC_SECTIONS = {
    "total_assets": "balance_sheet",
    "total_liabilities": "balance_sheet",
    "total_equity": "balance_sheet",
    "customer_loans_net": "balance_sheet",
    "customer_deposits": "balance_sheet",
    "net_income": "income_statement",
    "net_banking_income": "income_statement",
}


def _normalise(value: str) -> str:
    return " ".join(value.lower().replace("’", "'").split())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _document_and_pages(bank_id: str, year: int) -> tuple[dict[str, Any] | None, dict[int, str]]:
    root = PROJECT_ROOT / "data" / "normalized" / "corpus" / bank_id / str(year)
    documents_path = root / "documents.json"
    chunks_path = root / "evidence_chunks.jsonl"
    if not documents_path.exists() or not chunks_path.exists():
        return None, {}
    documents = json.loads(documents_path.read_text(encoding="utf-8"))
    document = next((item for item in documents if item["bank_id"] == bank_id and item["reporting_year"] == year), None)
    pages: dict[int, list[str]] = {}
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        chunk = json.loads(line)
        pages.setdefault(chunk["page_number"], []).append(chunk["text"])
    return document, {page: "\n".join(texts) for page, texts in pages.items()}


def validate_facts(payload: list[dict[str, Any]]) -> tuple[list[FinancialFact], dict[str, Any]]:
    """Validate provenance, units, uniqueness and core accounting identities.

    Only facts that pass every applicable deterministic control are returned.
    The report records every rejection, so extraction errors are never silently
    promoted or discarded.
    """
    reports: list[dict[str, Any]] = []
    accepted: list[FinancialFact] = []
    seen: Counter[tuple[str, int, str]] = Counter(
        (str(item.get("document_id")), int(item.get("reporting_year", 0)), str(item.get("metric_id")))
        for item in payload
    )
    cached_sources: dict[tuple[str, int], tuple[dict[str, Any] | None, dict[int, str]]] = {}
    source_hashes: dict[Path, str | None] = {}
    values: dict[str, Any] = {}
    allowed_metrics = set(load_common_extraction_profile()["metric_ids"])

    for raw in payload:
        checks: dict[str, bool] = {}
        reasons: list[str] = []
        bank_id = str(raw.get("document_id", "")).split("-", 1)[0]
        year = int(raw.get("reporting_year", 0))
        source_key = (bank_id, year)
        if source_key not in cached_sources:
            cached_sources[source_key] = _document_and_pages(*source_key)
        document, pages = cached_sources[source_key]

        try:
            fact = FinancialFact.model_validate(raw)
        except ValidationError as error:
            reports.append({"fact_id": raw.get("fact_id"), "status": "rejected", "checks": checks, "reasons": [str(error)]})
            continue

        checks["unique_metric_per_document"] = seen[(fact.document_id, fact.reporting_year, fact.metric_id)] == 1
        if not checks["unique_metric_per_document"]:
            reasons.append("The metric appears more than once in the same document.")

        checks["metric_is_in_common_catalog"] = fact.metric_id in allowed_metrics
        if not checks["metric_is_in_common_catalog"]:
            reasons.append("Metric is not in the approved common extraction catalog.")

        expected_section = _METRIC_SECTIONS.get(fact.metric_id)
        checks["section_matches_metric"] = expected_section is not None and fact.section == expected_section
        if not checks["section_matches_metric"]:
            reasons.append("The fact is not extracted from its expected primary financial statement.")

        checks["source_document_present"] = document is not None
        if document is None:
            reasons.append("No corpus document record exists for this bank and year.")
        else:
            checks["document_identity_matches"] = (
                fact.document_id == document["document_id"]
                and fact.source_path == document["source_path"]
                and fact.source_sha256 == document["sha256"]
            )
            if not checks["document_identity_matches"]:
                reasons.append("Fact provenance does not match the corpus document record.")
            source_pdf = PROJECT_ROOT / fact.source_path
            if source_pdf not in source_hashes:
                source_hashes[source_pdf] = _sha256(source_pdf) if source_pdf.exists() else None
            checks["source_pdf_hash_matches"] = source_hashes[source_pdf] == fact.source_sha256
            if not checks["source_pdf_hash_matches"]:
                reasons.append("The official PDF is missing or has changed since extraction.")

        page_text = pages.get(fact.page_number, "")
        checks["source_page_present"] = bool(page_text)
        checks["excerpt_found_on_source_page"] = bool(page_text) and _normalise(fact.source_excerpt) in _normalise(page_text)
        if not checks["excerpt_found_on_source_page"]:
            reasons.append("The recorded excerpt is not found on the cited PDF page.")

        checks["unit_is_supported"] = fact.currency == "TND" and fact.unit_scale in {"unit", "thousand", "million"}
        if not checks["unit_is_supported"]:
            reasons.append("Currency or unit scale is unsupported.")
        checks["scope_is_individual"] = fact.scope == "individual"
        if not checks["scope_is_individual"]:
            reasons.append("Only catalogued individual financial statements are in the current scope.")
        checks["value_is_numeric"] = fact.value.is_finite()
        if not checks["value_is_numeric"]:
            reasons.append("Financial value is not finite.")

        valid = all(checks.values())
        reports.append({
            "fact_id": fact.fact_id,
            "metric_id": fact.metric_id,
            "page_number": fact.page_number,
            "status": "auto_validated" if valid else "rejected",
            "checks": checks,
            "reasons": reasons,
        })
        if valid:
            accepted.append(fact.model_copy(update={"validation_status": "auto_validated"}))
            values[fact.metric_id] = fact.value

    balance_check: dict[str, Any] = {"applicable": False, "passed": None}
    balance_metrics = {"total_assets", "total_liabilities", "total_equity"}
    if balance_metrics.issubset(values):
        balance_check = {
            "applicable": True,
            "passed": values["total_assets"] == values["total_liabilities"] + values["total_equity"],
            "formula": "total_assets = total_liabilities + total_equity",
        }
        if not balance_check["passed"]:
            rejected_metrics = balance_metrics
            accepted = [fact for fact in accepted if fact.metric_id not in rejected_metrics]
            for item in reports:
                if item.get("metric_id") in rejected_metrics and item["status"] == "auto_validated":
                    item["status"] = "rejected"
                    item["reasons"].append("Balance-sheet equation failed.")

    report = {
        "validation_engine": "deterministic-v2",
        "input_fact_count": len(payload),
        "auto_validated_fact_count": len(accepted),
        "rejected_fact_count": len(payload) - len(accepted),
        "report_level_checks": {"balance_equation": balance_check},
        "facts": reports,
    }
    return accepted, report


def write_validation_run(bank_id: str, year: int, payload: list[dict[str, Any]]) -> tuple[list[FinancialFact], dict[str, Any]]:
    """Persist the only answerable dataset and its complete validation report."""
    accepted, report = validate_facts(payload)
    facts_path = AUTO_VALIDATED_ROOT / bank_id / str(year) / "financial_facts.json"
    run_root = VALIDATION_RUNS_ROOT / bank_id / str(year)
    facts_path.parent.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)
    facts_path.write_text(
        json.dumps([fact.model_dump(mode="json") for fact in accepted], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (run_root / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rejected = [item for item in report["facts"] if item["status"] == "rejected"]
    (run_root / "rejected_facts.json").write_text(json.dumps(rejected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return accepted, report
