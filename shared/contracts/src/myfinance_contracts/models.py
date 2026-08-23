"""Stable, dependency-light contracts shared by the MyFinance services."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    bank_id: str
    bank_name: str
    year: int
    path: str
    source_type: str = "annual_financial_statement"


class MarketDataSource(BaseModel):
    """Declared authority before any market ingestion is allowed."""

    source_id: str
    name: str
    authority_kind: Literal["exchange", "regulator", "issuer"]
    base_url: str
    data_kinds: list[Literal["price", "market_summary", "volume", "disclosure", "corporate_action"]]
    update_frequency: str
    activation_status: Literal["candidate", "verified", "active", "disabled"]
    activation_requirements: list[str] = Field(default_factory=list)


class MarketObservation(BaseModel):
    """One dated, auditable market datapoint accepted by the future agent."""

    instrument_id: str
    # ``reference_price`` is deliberately distinct from ``close_price``.
    # An exchange may publish a previous-session reference alongside a latest
    # traded price. Collapsing them would make an answer look precise while
    # silently changing its meaning.
    field: Literal[
        "last_price",
        "reference_price",
        "close_price",
        "open_price",
        "high_price",
        "low_price",
        "volume",
        "session_change_percent",
    ]
    value: Decimal
    currency: str | None = None
    observed_at: datetime
    retrieved_at: datetime
    source_id: str
    source_url: str
    source_published_at: datetime | None = None
    verification_status: Literal["candidate", "verified"] = "candidate"


class MarketInstrument(BaseModel):
    """Mapping between a bank in the report corpus and a market instrument."""

    bank_id: str
    bank_name: str
    listing_status: Literal["listed", "not_mapped"]
    exchange: str | None = None
    exchange_symbol: str | None = None
    instrument_id: str | None = None
    identity_status: Literal["pending_verification", "verified"]
    verification_url: str | None = None


class DocumentRecord(BaseModel):
    document_id: str
    bank_id: str
    bank_name: str
    reporting_year: int
    source_path: str
    sha256: str
    page_count: int
    document_type: str = "annual_financial_statement"


class EvidenceChunk(BaseModel):
    chunk_id: str
    document_id: str
    bank_id: str
    bank_name: str
    reporting_year: int
    page_number: int
    section: str
    source_path: str
    source_sha256: str
    text: str


class FinancialFact(BaseModel):
    fact_id: str
    metric_id: str
    raw_label: str
    value: Decimal
    currency: str
    unit_scale: Literal["unit", "thousand", "million"]
    reporting_year: int
    period_kind: str = "annual"
    scope: str | None = None
    document_id: str
    source_path: str
    source_sha256: str
    page_number: int
    section: str
    source_excerpt: str
    # `verified` remains readable only for historical BIAT files.  New facts
    # become answerable exclusively through the deterministic auto-validation gate.
    validation_status: Literal["candidate", "auto_validated", "rejected", "verified"] = "candidate"


class RequestAssessment(BaseModel):
    decision: Literal["answer", "clarify", "abstain"]
    reason: str
    missing_information: list[str] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
    detected_banks: list[str] = Field(default_factory=list)
    detected_years: list[int] = Field(default_factory=list)
    detected_metric: str | None = None


class ReportedValueAnswer(BaseModel):
    metric_id: str
    value: Decimal
    currency: str
    unit_scale: str
    reporting_year: int
    source_document: str
    page_number: int
    source_excerpt: str


ConversationMode = Literal["idle", "general", "metric", "comparison", "document", "market"]


class ConversationContext(BaseModel):
    mode: ConversationMode = "idle"
    bank_id: str | None = None
    bank_name: str | None = None
    reporting_year: int | None = None
    topic: str | None = None
    # A machine-readable subject survives short follow-ups even when the user
    # writes without accents or only says “les autres”.
    document_scope: str | None = None
    document_anchor: str | None = None
    document_anchor_page: int | None = None
    # A documentary search remembers only its latest query and outcome.  This
    # prevents an ambiguous follow-up from silently replaying the same failed
    # retrieval as though it were a fresh attempt.
    document_query: str | None = None
    document_search_status: Literal["found", "no_evidence"] | None = None
    metric_id: str | None = None
    # Retain at most the two banks discussed for the active metric so that a
    # natural follow-up such as “compare them” has an unambiguous referent.
    metric_bank_ids: list[str] = Field(default_factory=list)
    comparison_bank_ids: list[str] = Field(default_factory=list)
    # The comparison dossier retains a short, ordered metric history.  This
    # lets a later request such as “analyse all the metrics we discussed” refer
    # to explicit prior comparisons without storing the whole chat transcript.
    comparison_metric_ids: list[str] = Field(default_factory=list)
    # The market service keeps its own source and observation lifecycle.  The
    # router only retains the referenced banks, never a live price or a report
    # value, so a follow-up cannot accidentally cross those two domains.
    market_bank_ids: list[str] = Field(default_factory=list)
    # General education keeps a deliberately short memory: enough for natural
    # follow-ups, without retaining a full unbounded chat transcript.
    general_last_answer: str | None = None


class ConversationRequest(BaseModel):
    message: str
    context: ConversationContext = Field(default_factory=ConversationContext)
