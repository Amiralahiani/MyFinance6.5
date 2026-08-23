"""Explicit collection boundary for auditable Market Watch snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from myfinance_contracts import MarketObservation

from myfinance_agent_market.market_watch_reader import current_market_quotes
from myfinance_agent_market.storage import MarketObservationStore

PROJECT_ROOT = Path(__file__).resolve().parents[4]
MARKET_SNAPSHOTS_ROOT = PROJECT_ROOT / "data" / "market-snapshots"
MARKET_COLLECTION_RUNS_ROOT = PROJECT_ROOT / "data" / "market-collection-runs"
OFFICIAL_SOURCE_ID = "tunis_stock_exchange_official"


def collect_current_market_snapshot(
    bank_ids: list[str],
    *,
    root: Path = MARKET_SNAPSHOTS_ROOT,
) -> dict[str, Any]:
    """Fetch current official quotes once and persist an immutable snapshot.

    This is deliberately separate from chat reads: asking a question must not
    create data.  A scheduler invokes this function at the desired cadence.
    """
    quotes = current_market_quotes(bank_ids)
    if not quotes:
        raise ValueError("At least one bank is required for market collection.")
    retrieved_at = _retrieval_time(quotes)
    observations: list[MarketObservation] = []
    for quote in quotes:
        observations.extend(_quote_observations(quote, retrieved_at))
    destination = MarketObservationStore(root).save_snapshot(observations, retrieved_at=retrieved_at)
    return {
        "snapshot_path": str(destination),
        "retrieved_at": retrieved_at.isoformat(),
        "bank_ids": [str(quote["bank_id"]) for quote in quotes],
        "observation_count": len(observations),
        "source_id": OFFICIAL_SOURCE_ID,
    }


def record_collection_run(
    status: str,
    *,
    started_at: datetime,
    finished_at: datetime,
    details: dict[str, Any] | None = None,
    root: Path = MARKET_COLLECTION_RUNS_ROOT,
) -> Path:
    """Persist the outcome of one scheduler run for health checks and alerts."""
    if status not in {"succeeded", "failed"}:
        raise ValueError("Collection run status must be 'succeeded' or 'failed'.")
    finished = finished_at.astimezone(UTC)
    started = started_at.astimezone(UTC)
    folder = root / finished.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "status": status,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "details": details or {},
    }
    destination = folder / f"run-{finished.strftime('%Y%m%dT%H%M%SZ')}.json"
    _write_json_atomically(destination, payload)
    _write_json_atomically(root / "latest.json", payload)
    return destination


def latest_collection_run(
    root: Path = MARKET_COLLECTION_RUNS_ROOT,
) -> dict[str, Any] | None:
    """Return the latest persisted scheduler outcome, ignoring invalid local files."""
    path = root / "latest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and payload.get("status") in {"succeeded", "failed"} else None


def _quote_observations(quote: dict[str, Any], retrieved_at: datetime) -> list[MarketObservation]:
    currency = str(quote["currency"])
    common = {
        "instrument_id": f"BVMT:{quote['mnemonic']}",
        "observed_at": retrieved_at,
        "retrieved_at": retrieved_at,
        "source_id": OFFICIAL_SOURCE_ID,
        "source_url": str(quote["source_url"]),
        "verification_status": "verified",
    }
    return [
        MarketObservation(field="last_price", value=Decimal(str(quote["price"])), currency=currency, **common),
        MarketObservation(
            field="session_change_percent",
            value=Decimal(str(quote["change_percent"])),
            currency=None,
            **common,
        ),
    ]


def _retrieval_time(quotes: list[dict[str, Any]]) -> datetime:
    values = {str(quote.get("retrieved_at", "")) for quote in quotes}
    if len(values) != 1:
        raise ValueError("A collection must contain quotes retrieved at one timestamp.")
    value = values.pop()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("The official reader returned no valid retrieval timestamp.") from error
    return parsed.astimezone(UTC)


def _write_json_atomically(destination: Path, payload: dict[str, Any]) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
