"""Run one auditable official Market Watch collection for a scheduler."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "shared" / "contracts" / "src"),
    str(ROOT / "chat" / "knowledge" / "src"),
    str(ROOT / "chat" / "market" / "src"),
]


def _positive_minutes(value: str) -> int:
    minutes = int(value)
    if minutes <= 0:
        raise argparse.ArgumentTypeError("The interval must be greater than zero.")
    return minutes


def _collect_once(bank_ids: list[str]) -> bool:
    """Collect once, recording both success and failure for monitoring."""
    from myfinance_agent_market.collector import (
        collect_current_market_snapshot,
        record_collection_run,
    )

    started_at = datetime.now(UTC)
    try:
        result = collect_current_market_snapshot(bank_ids)
    except (OSError, RuntimeError, ValueError) as error:
        finished_at = datetime.now(UTC)
        details = {
            "bank_ids": bank_ids,
            "error_type": type(error).__name__,
            "error": " ".join(str(error).split())[:500],
        }
        try:
            record_collection_run("failed", started_at=started_at, finished_at=finished_at, details=details)
        except OSError as logging_error:
            print(f"Could not record collection failure: {logging_error}", file=sys.stderr)
        print(json.dumps(details, ensure_ascii=False), file=sys.stderr)
        return False

    finished_at = datetime.now(UTC)
    record_collection_run("succeeded", started_at=started_at, finished_at=finished_at, details=result)
    print(json.dumps(result, ensure_ascii=False))
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "bank_ids",
        nargs="*",
        help="Optional bank ids; without them, collect every verified listed bank.",
    )
    parser.add_argument(
        "--interval-minutes",
        type=_positive_minutes,
        help="Run continuously at this cadence; without it, collect once and exit.",
    )
    args = parser.parse_args()
    from myfinance_agent_market.sources import market_instrument_registry

    bank_ids = args.bank_ids or [
        instrument.bank_id
        for instrument in market_instrument_registry()
        if instrument.listing_status == "listed" and instrument.identity_status == "verified"
    ]
    if not bank_ids:
        parser.error("No verified listed bank is configured for collection.")
    if args.interval_minutes is None:
        if not _collect_once(bank_ids):
            raise SystemExit(1)
        return

    interval_seconds = args.interval_minutes * 60
    next_run = time.monotonic()
    while True:
        _collect_once(bank_ids)
        next_run += interval_seconds
        try:
            time.sleep(max(0.0, next_run - time.monotonic()))
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
