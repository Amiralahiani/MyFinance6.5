"""Market agent: source registry first, no market observation before verification."""

from typing import Annotated

from fastapi import FastAPI, Query

from myfinance_agent_market.availability import market_answer_availability
from myfinance_agent_market.monitoring import collection_health
from myfinance_agent_market.sources import (
    active_market_sources,
    market_collection_plan,
    market_instrument_registry,
    market_source_registry,
)

app = FastAPI(title="MyFinance Market Agent", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-market"}


@app.get("/status")
async def status() -> dict[str, object]:
    policy, sources = market_source_registry()
    active = active_market_sources()
    verified = [source for source in sources if source.activation_status == "verified"]
    return {
        "status": "market_answers_ready" if active else "ingestion_ready_answers_disabled" if verified else "sources_declared_not_active",
        "policy": policy,
        "active_source_ids": [source.source_id for source in active],
        "verified_source_ids": [source.source_id for source in verified],
        "configured_sources": [
            {"source_id": source.source_id, "name": source.name, "status": source.activation_status}
            for source in sources
        ],
        "collection_health": collection_health(),
    }


@app.get("/sources")
async def sources() -> list[dict[str, object]]:
    _, configured = market_source_registry()
    return [source.model_dump() for source in configured]


@app.get("/instruments")
async def instruments() -> list[dict[str, object]]:
    return [instrument.model_dump() for instrument in market_instrument_registry()]


@app.get("/collection-plan/{bank_id}")
async def collection_plan(bank_id: str) -> dict[str, object]:
    return market_collection_plan(bank_id)


@app.get("/answer-availability")
async def answer_availability(bank_id: Annotated[list[str] | None, Query()] = None) -> dict[str, object]:
    """Expose the same no-fetch authorisation boundary used by the chat."""
    return market_answer_availability(bank_id or [])


@app.get("/collection-health")
async def collection_status() -> dict[str, object]:
    """Expose collector freshness without requesting Market Watch."""
    return collection_health()
