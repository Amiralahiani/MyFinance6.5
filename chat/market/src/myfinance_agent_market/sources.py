"""Versioned, source-first registry for the market agent."""

from __future__ import annotations

import json
from pathlib import Path

from myfinance_contracts import MarketDataSource, MarketInstrument

PROJECT_ROOT = Path(__file__).resolve().parents[4]
MARKET_SOURCES_PATH = PROJECT_ROOT / "data" / "reference" / "market_sources.json"
MARKET_INSTRUMENTS_PATH = PROJECT_ROOT / "data" / "reference" / "market_instruments.json"


def market_source_registry() -> tuple[dict[str, object], list[MarketDataSource]]:
    """Load declared sources without contacting them or accepting observations."""
    payload = json.loads(MARKET_SOURCES_PATH.read_text(encoding="utf-8"))
    policy = dict(payload["policy"])
    sources = [MarketDataSource.model_validate(item) for item in payload["sources"]]
    return policy, sources


def active_market_sources() -> list[MarketDataSource]:
    """Only explicit active sources may later feed user-facing market answers."""
    _, sources = market_source_registry()
    return [source for source in sources if source.activation_status == "active"]


def market_instrument_registry() -> list[MarketInstrument]:
    """Load only verified identity mappings; this function does not fetch prices."""
    payload = json.loads(MARKET_INSTRUMENTS_PATH.read_text(encoding="utf-8"))
    return [MarketInstrument.model_validate(item) for item in payload["instruments"]]


def market_collection_plan(bank_id: str) -> dict[str, object]:
    """Describe the authorised future collection path without accessing a feed."""
    instrument = next((item for item in market_instrument_registry() if item.bank_id == bank_id), None)
    if instrument is None or instrument.listing_status != "listed" or instrument.identity_status != "verified":
        return {
            "status": "instrument_not_available",
            "bank_id": bank_id,
            "reason": "No verified listed instrument is mapped for this bank.",
        }
    source = next((item for item in market_source_registry()[1] if "price" in item.data_kinds), None)
    if source is None or source.activation_status not in {"verified", "active"}:
        return {
            "status": "waiting_for_source_verification",
            "bank_id": bank_id,
            "reason": "The official source has not passed collection verification.",
        }
    return {
        "status": "ready_for_collection" if source.activation_status == "verified" else "active",
        "bank_id": bank_id,
        "instrument": instrument.model_dump(),
        "required_observation_fields": [
            "last_price", "reference_price", "observed_at", "retrieved_at", "source_url", "verification_status"
        ],
        "source_id": source.source_id,
        "user_answers_enabled": source.activation_status == "active",
    }
