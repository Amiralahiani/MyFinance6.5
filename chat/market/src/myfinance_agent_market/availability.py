"""Read-only capability boundary between the market agent and the chat router."""

from __future__ import annotations

from collections.abc import Iterable

from myfinance_agent_market.sources import (
    active_market_sources,
    market_instrument_registry,
    market_source_registry,
)


def market_answer_availability(bank_ids: Iterable[str] = ()) -> dict[str, object]:
    """Describe whether a user-facing market answer is currently authorised.

    This function never fetches a quote.  It is intentionally the only market
    capability exposed to the conversation router until the next phase adds a
    reader for persisted, dated observations.
    """
    requested_ids = list(dict.fromkeys(bank_ids))
    instruments = {instrument.bank_id: instrument for instrument in market_instrument_registry()}
    _, configured_sources = market_source_registry()
    active_sources = active_market_sources()
    requested = [instruments[bank_id] for bank_id in requested_ids if bank_id in instruments]

    return {
        "status": "market_answers_ready" if active_sources else "market_answers_disabled",
        "active": bool(active_sources),
        "active_source_ids": [source.source_id for source in active_sources],
        "verified_source_ids": [
            source.source_id for source in configured_sources if source.activation_status == "verified"
        ],
        "requested_instruments": [instrument.model_dump() for instrument in requested],
        "unmapped_bank_ids": [
            instrument.bank_id
            for instrument in requested
            if instrument.listing_status != "listed" or instrument.identity_status != "verified"
        ],
        "reason": (
            "No market source is active for user-facing answers."
            if not active_sources
            else "An active market source exists; answers also require a dated stored observation."
        ),
    }
