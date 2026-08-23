"""Build the optional Qdrant index from the already validated local corpus."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "shared" / "contracts" / "src"),
    str(ROOT / "chat" / "knowledge" / "src"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Index MyFinance evidence chunks in Qdrant.")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all", action="store_true", help="Index every report currently in the local corpus.")
    scope.add_argument("--bank", help="Index one bank; requires --year.")
    parser.add_argument("--year", type=int, help="Reporting year required with --bank.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Number of evidence chunks embedded per request (default: 8).",
    )
    args = parser.parse_args()
    if args.bank and args.year is None:
        parser.error("--year is required when --bank is used.")
    if args.batch_size < 1:
        parser.error("--batch-size must be greater than zero.")

    from myfinance_agent_docs.catalog import load_catalog
    from myfinance_agent_docs.corpus import load_evidence_chunks
    from myfinance_agent_docs.vector_store import QdrantVectorStore, VectorStoreUnavailable

    reports = load_catalog() if args.all else [report for report in load_catalog() if report.bank_id == args.bank and report.year == args.year]
    if not reports:
        parser.error("No matching report is available in the local corpus.")
    store = QdrantVectorStore()
    total = 0
    try:
        for report in reports:
            chunks = load_evidence_chunks(report.bank_id, report.year)
            count = store.index_chunks(chunks, batch_size=args.batch_size)
            total += count
            print(f"Indexed {count} chunks for {report.bank_id} {report.year}.")
    except VectorStoreUnavailable as error:
        raise SystemExit(f"Indexing aborted: {error}") from error
    print(f"Indexed {total} chunks in Qdrant collection '{store.settings.collection}'.")


if __name__ == "__main__":
    main()
