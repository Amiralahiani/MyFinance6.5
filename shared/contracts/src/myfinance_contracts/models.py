"""Stable, dependency-light contracts shared by the MyFinance services."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    bank_id: str
    bank_name: str
    year: int
    path: str
    source_type: str = "annual_financial_statement"


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


ConversationMode = Literal["idle", "metric", "document"]


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
    metric_id: str | None = None


class ConversationRequest(BaseModel):
    message: str
    context: ConversationContext = Field(default_factory=ConversationContext)
