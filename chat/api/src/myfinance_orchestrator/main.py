"""FastAPI entry point for the first reliable request-routing contract."""

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from myfinance_agent_docs.catalog import REPORTS_ROOT, load_catalog
from myfinance_agent_docs.corpus import retrieve_evidence
from myfinance_agent_docs.facts import auto_validated_fact
from myfinance_agent_market.availability import market_answer_availability
from myfinance_agent_market.monitoring import collection_health
from myfinance_contracts import (
    ConversationRequest,
    ReportedValueAnswer,
    RequestAssessment,
    SlidingWindowRateLimiter,
    load_runtime_security_settings,
)
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from myfinance_orchestrator.assessment import assess_request
from myfinance_orchestrator.dialogue import (
    ROUTER_REVISION,
    _classify_requested_bank_scope,
    _conversation_router_enabled,
    _turn_plan,
    answer_conversation_turn,
)
from myfinance_orchestrator.evidence_synthesis import answer_from_evidence
from myfinance_orchestrator.language import normalise_financial_request
from myfinance_orchestrator.model_provider import MODEL, PROVIDER, USE_LLM

RUNTIME_SECURITY = load_runtime_security_settings()
RATE_LIMITER = SlidingWindowRateLimiter(RUNTIME_SECURITY.rate_limit_per_minute)

app = FastAPI(title="MyFinance Orchestrator", version="0.1.0")
if RUNTIME_SECURITY.is_public:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(RUNTIME_SECURITY.allowed_hosts))
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(RUNTIME_SECURITY.cors_origins),
    allow_origin_regex=(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$" if not RUNTIME_SECURITY.is_public else None),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def apply_runtime_protections(request: Request, call_next):
    """Set conservative headers and bound public traffic before route execution."""
    client_id = request.client.host if request.client else "unknown"
    if request.url.path != "/health" and not RATE_LIMITER.allows(client_id):
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please retry in one minute."},
            headers={"Retry-After": "60"},
        )
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/api/status")
async def service_status() -> dict[str, object]:
    """Expose non-sensitive runtime configuration for local diagnosis."""
    if RUNTIME_SECURITY.is_public:
        return {"status": "ok", "service": "orchestrator"}
    return {
        "llm_provider": PROVIDER,
        "llm_model": MODEL,
        "llm_enabled": USE_LLM,
        "conversation_router_enabled": _conversation_router_enabled(),
        "router_revision": ROUTER_REVISION,
    }


@app.get("/api/market/status")
async def market_status(bank_id: Annotated[list[str] | None, Query()] = None) -> dict[str, object]:
    """Expose market-answer readiness without fetching a quote or touching reports."""
    return market_answer_availability(bank_id or [])


@app.get("/api/market/collection-health")
async def market_collection_health() -> dict[str, object]:
    """Report whether the scheduled market collector is delivering fresh data."""
    return collection_health()


@app.post("/api/diagnostics/plan")
async def diagnose_turn_plan(body: ConversationRequest) -> dict[str, object]:
    """Return the validated routing plan without accessing any report content."""
    if RUNTIME_SECURITY.is_public:
        raise HTTPException(status_code=404, detail="Not found.")
    message, corrections = normalise_financial_request(body.message)
    assessment = assess_request(message)
    return {
        "message": message,
        "normalization": corrections,
        "assessment": assessment.model_dump(),
        "bank_scope_guard": _classify_requested_bank_scope(body.message),
        "plan": _turn_plan(body.message, body.context, assessment),
    }
app.mount("/documents", StaticFiles(directory=REPORTS_ROOT), name="official-documents")


class UserRequest(BaseModel):
    message: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "orchestrator"}


@app.post("/api/requests/normalize")
async def normalize_request(body: UserRequest) -> dict:
    """Normalize a complete request before it is assessed against source reports."""
    message, corrections = normalise_financial_request(body.message)
    return {"message": message, "corrections": corrections}


@app.post("/api/conversation/answer")
async def answer_conversation(body: ConversationRequest) -> dict:
    """Answer a turn from its active dossier before considering metric lookup."""
    message, corrections = normalise_financial_request(body.message)
    try:
        result = answer_conversation_turn(message, body.context, routing_message=body.message)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    result["normalization"] = {"message": message, "corrections": corrections}
    return result


@app.get("/api/reports")
async def reports():
    """List source reports before any PDF extraction or LLM use."""
    return {"reports": load_catalog()}


@app.post("/api/requests/assess", response_model=RequestAssessment)
async def assess(body: UserRequest) -> RequestAssessment:
    """Decide whether a request can be answered safely, needs clarification, or must stop."""
    return assess_request(body.message)


@app.post("/api/requests/answer", response_model=ReportedValueAnswer)
async def answer_reported_value(body: UserRequest) -> ReportedValueAnswer:
    """Answer one reported value only when automatic validation and PDF proof exist."""
    assessment = assess_request(body.message)
    if assessment.decision != "answer" or len(assessment.detected_banks) != 1 or len(assessment.detected_years) != 1:
        raise HTTPException(status_code=422, detail=assessment.model_dump())
    fact = auto_validated_fact(
        assessment.detected_banks[0],
        assessment.detected_years[0],
        assessment.detected_metric or "",
    )
    if fact is None:
        raise HTTPException(
            status_code=404,
            detail="This metric has not yet passed automatic validation for this report; no value is invented.",
        )
    return ReportedValueAnswer(
        metric_id=fact.metric_id,
        value=fact.value,
        currency=fact.currency,
        unit_scale=fact.unit_scale,
        reporting_year=fact.reporting_year,
        source_document=fact.source_path,
        page_number=fact.page_number,
        source_excerpt=fact.source_excerpt,
    )


@app.post("/api/requests/documents/search")
async def search_documents(body: UserRequest) -> dict:
    """Retrieve official PDF passages for a documentary question; never invent an answer."""
    assessment = assess_request(body.message)
    if len(assessment.detected_banks) != 1 or len(assessment.detected_years) != 1:
        raise HTTPException(status_code=422, detail=assessment.model_dump())
    bank_id, year = assessment.detected_banks[0], assessment.detected_years[0]
    evidence = retrieve_evidence(bank_id, year, body.message, limit=2, include_neighbour_pages=True)
    if not evidence:
        raise HTTPException(
            status_code=404,
            detail="No sufficiently relevant excerpt was found in this report.",
        )
    return {
        "mode": "documentary_evidence",
        "bank_id": bank_id,
        "reporting_year": year,
        "evidence": [chunk.model_dump() for chunk in evidence],
    }


@app.post("/api/requests/documents/answer")
async def answer_from_documents(body: UserRequest) -> dict:
    """Give a grounded explanation generated only from retrieved report passages."""
    assessment = assess_request(body.message)
    if len(assessment.detected_banks) != 1 or len(assessment.detected_years) != 1:
        raise HTTPException(status_code=422, detail=assessment.model_dump())
    bank_id, year = assessment.detected_banks[0], assessment.detected_years[0]
    evidence = retrieve_evidence(bank_id, year, body.message, limit=2, include_neighbour_pages=True)
    if not evidence:
        raise HTTPException(status_code=404, detail="No sufficiently relevant excerpt was found in this report.")
    try:
        answer = answer_from_evidence(body.message, evidence)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {
        "mode": "documentary_answer",
        "bank_id": bank_id,
        "reporting_year": year,
        "answer": answer,
        "evidence": [chunk.model_dump() for chunk in evidence],
    }
