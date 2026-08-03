"""HTTP surface of the document agent; PDF extraction is the next implementation step."""

from fastapi import FastAPI

from myfinance_agent_docs.catalog import load_catalog

app = FastAPI(title="MyFinance Document Agent", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-docs"}


@app.get("/documents/catalog")
async def document_catalog():
    """Expose the deterministic list of source reports known to the system."""
    return {"reports": load_catalog()}
