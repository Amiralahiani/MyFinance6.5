"""Command line entry point for deterministic report ingestion."""

from __future__ import annotations

import argparse
from pathlib import Path

from myfinance_agent_docs.catalog import PROJECT_ROOT, bank_definitions, load_catalog
from myfinance_agent_docs.facts import extract_candidate_facts
from myfinance_agent_docs.ingestion import write_corpus
from myfinance_agent_docs.validation import write_validation_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract traceable evidence chunks from bank PDFs.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "normalized" / "corpus",
        help="Corpus root; each report is written to <bank>/<year> beneath this directory.",
    )
    parser.add_argument(
        "--bank",
        choices=sorted(bank_definitions()),
        help="Limit ingestion to one bank.",
    )
    parser.add_argument(
        "--year",
        type=int,
        choices=range(2021, 2026),
        help="Limit ingestion to one reporting year; requires --bank.",
    )
    parser.add_argument(
        "--extract-and-validate",
        action="store_true",
        help="Extract facts in memory and publish only those that pass deterministic validation; requires --bank and --year.",
    )
    args = parser.parse_args()
    if args.year and not args.bank:
        parser.error("--year requires --bank")
    if args.extract_and_validate and not (args.bank and args.year):
        parser.error("--extract-and-validate requires --bank and --year")
    selected_reports = load_catalog()
    if args.bank:
        selected_reports = [report for report in selected_reports if report.bank_id == args.bank]
    if args.year:
        selected_reports = [report for report in selected_reports if report.year == args.year]

    total_documents = 0
    total_chunks = 0
    for report in selected_reports:
        output = args.output / report.bank_id / str(report.year)
        documents, chunks = write_corpus(output, [report])
        total_documents += documents
        total_chunks += chunks
        print(f"Ingested {documents} document into {chunks} source-preserving chunks: {output}")
    print(f"Completed: {total_documents} documents and {total_chunks} chunks.")
    if args.extract_and_validate:
        report = selected_reports[0]
        extracted = extract_candidate_facts(report)
        facts, validation_report = write_validation_run(
            report.bank_id,
            report.year,
            [fact.model_dump(mode="json") for fact in extracted],
        )
        print(
            f"Published {len(facts)} auto-validated facts; "
            f"{validation_report['rejected_fact_count']} rejected by deterministic checks."
        )


if __name__ == "__main__":
    main()
