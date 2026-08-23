"""Official Bourse de Tunis Market Watch collection boundary."""

from __future__ import annotations

MARKET_WATCH_URL = "https://tunis-stockexchange.com/market-watch"


def market_watch_collection_status() -> dict[str, str]:
    """Describe the explicit, scheduled collection route without fetching."""
    return {
        "source_id": "tunis_stock_exchange_official",
        "status": "scheduled_snapshot_collection_ready",
        "source_url": MARKET_WATCH_URL,
        "reason": "The official reader captures the displayed public quote; a scheduler persists each verified collection as an immutable snapshot.",
    }
