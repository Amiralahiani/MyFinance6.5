"""Run repeatable automatic validation for all catalogued bank reports.

This command regenerates the source-preserving corpus, a section index and
in-memory extracted facts.  The deterministic validation gate then either
publishes facts to ``facts/auto_validated`` or records rejections.  The API
never reads intermediate extraction output.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "shared" / "contracts" / "src"),
    str(ROOT / "chat" / "knowledge" / "src"),
]

from myfinance_agent_docs.catalog import load_catalog, load_common_extraction_profile
from myfinance_agent_docs.facts import extract_candidate_facts
from myfinance_agent_docs.ingestion import write_corpus
from myfinance_agent_docs.section_index import write_section_index
from myfinance_agent_docs.validation import (
    AUTO_VALIDATED_ROOT,
    VALIDATION_RUNS_ROOT,
    write_validation_run,
)

CORPUS_ROOT = ROOT / "data" / "normalized" / "corpus"
REVIEW_PATH = ROOT / "data" / "reference" / "bank_validation_review_queue.json"
CORE_METRICS = tuple(load_common_extraction_profile()["metric_ids"])


def selected_reports(bank_ids: set[str], years: set[int]) -> list:
    reports = [report for report in load_catalog() if report.bank_id in bank_ids]
    return [report for report in reports if not years or report.year in years]


def build_report(report) -> dict[str, object]:
    corpus_dir = CORPUS_ROOT / report.bank_id / str(report.year)
    document_count, chunk_count = write_corpus(corpus_dir, [report])
    index_path = write_section_index(report.bank_id, report.year)
    extracted = extract_candidate_facts(report)
    validated, validation_report = write_validation_run(
        report.bank_id,
        report.year,
        [fact.model_dump(mode="json") for fact in extracted],
    )
    detected_metrics = sorted(fact.metric_id for fact in extracted)
    return {
        "bank_id": report.bank_id,
        "bank_name": report.bank_name,
        "reporting_year": report.year,
        "source_path": report.path,
        "corpus": {
            "document_count": document_count,
            "chunk_count": chunk_count,
            "section_index_path": index_path.relative_to(ROOT).as_posix(),
        },
        "extracted_metrics": detected_metrics,
        "missing_core_metrics": [metric for metric in CORE_METRICS if metric not in detected_metrics],
        "auto_validated_fact_count": len(validated),
        "rejected_fact_count": validation_report["rejected_fact_count"],
        "auto_validated_path": (AUTO_VALIDATED_ROOT / report.bank_id / str(report.year) / "financial_facts.json").relative_to(ROOT).as_posix(),
        "validation_report_path": (VALIDATION_RUNS_ROOT / report.bank_id / str(report.year) / "report.json").relative_to(ROOT).as_posix(),
        "review_status": (
            "no_extractable_facts"
            if not extracted
            else "rejected_facts_recorded"
            if validation_report["rejected_fact_count"]
            else "auto_validated_with_missing_core_metrics"
            if len(detected_metrics) != len(CORE_METRICS)
            else "auto_validated"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate extracted bank facts against their official PDFs.")
    parser.add_argument(
        "--bank",
        action="append",
        dest="banks",
        help="Bank identifier to process; repeatable. Omit to process all five banks.",
    )
    parser.add_argument("--year", action="append", dest="years", type=int, help="Reporting year to process; repeatable.")
    args = parser.parse_args()

    bank_ids = set(args.banks) if args.banks else {report.bank_id for report in load_catalog()}
    reports = selected_reports(bank_ids, set(args.years or []))
    if not reports:
        raise SystemExit("No official reports match the selected banks and years.")

    items = [build_report(report) for report in reports]
    by_bank = dict(sorted(Counter(item["bank_id"] for item in items).items()))
    payload = {
        "version": "2.0",
        "scope": "Automatic extraction and deterministic validation for the common core metrics in individual financial statements of five banks",
        "source_of_truth": "The official PDF remains the primary proof; only auto_validated facts are answerable values.",
        "total_reports": len(items),
        "core_metric_slots": len(items) * len(CORE_METRICS),
        "extracted_fact_count": sum(len(item["extracted_metrics"]) for item in items),
        "missing_core_metric_count": sum(len(item["missing_core_metrics"]) for item in items),
        "auto_validated_fact_count": sum(int(item["auto_validated_fact_count"]) for item in items),
        "rejected_fact_count": sum(int(item["rejected_fact_count"]) for item in items),
        "reports_by_bank": by_bank,
        "review_states": dict(sorted(Counter(item["review_status"] for item in items).items())),
        "items": items,
    }
    temporary = REVIEW_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(REVIEW_PATH)
    print(f"Processed {len(items)} reports through automatic validation: {REVIEW_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
