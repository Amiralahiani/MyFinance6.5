"""Market agent scaffold: it refuses to manufacture market context before sources exist."""

from fastapi import FastAPI

app = FastAPI(title="MyFinance Market Agent", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-market"}


@app.get("/status")
async def status() -> dict[str, str]:
    return {
        "status": "not_ready",
        "reason": "No dated and verified market data source has been configured yet.",
    }
