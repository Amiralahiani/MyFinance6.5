"""FastAPI entry point for the first reliable request-routing contract."""


from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from myfinance_agent_docs.catalog import REPORTS_ROOT, load_catalog
from myfinance_agent_docs.corpus import retrieve_evidence
from myfinance_agent_docs.facts import auto_validated_fact
from myfinance_contracts import ConversationRequest, ReportedValueAnswer, RequestAssessment
from pydantic import BaseModel

from myfinance_orchestrator.assessment import assess_request
from myfinance_orchestrator.dialogue import answer_conversation_turn
from myfinance_orchestrator.language import correct_financial_spelling
from myfinance_orchestrator.ollama import answer_from_evidence

app = FastAPI(title="MyFinance Orchestrator", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.mount("/documents", StaticFiles(directory=REPORTS_ROOT), name="official-documents")


class UserRequest(BaseModel):
    message: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "orchestrator"}


@app.post("/api/requests/normalize")
async def normalize_request(body: UserRequest) -> dict:
    """Repair only unambiguous spelling errors in known financial vocabulary."""
    message, corrections = correct_financial_spelling(body.message)
    return {"message": message, "corrections": corrections}


@app.post("/api/conversation/answer")
async def answer_conversation(body: ConversationRequest) -> dict:
    """Answer a turn from its active dossier before considering metric lookup."""
    message, corrections = correct_financial_spelling(body.message)
    try:
        result = answer_conversation_turn(message, body.context)
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
