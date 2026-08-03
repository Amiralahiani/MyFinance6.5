"""JSON-serialisable contracts exchanged by the autonomous testing loop.

Agents may suggest objectives or actions, but every output is first validated by
these models.  The contracts deliberately contain no secret, browser object or
live network connection: a campaign can therefore be replayed and audited from
its persisted JSONL traces.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Channel(StrEnum):
    API = "api"
    WEB = "web"


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    INCONCLUSIVE = "inconclusive"


class TestCategory(StrEnum):
    FINANCIAL_FACT = "financial_fact"
    SOURCE = "source"
    TEMPORAL = "temporal"
    UNIT = "unit"
    ARITHMETIC = "arithmetic"
    CONVERSATION = "conversation"
    REFORMULATION = "reformulation"
    ABSENCE = "absence"
    CROSS_CHANNEL = "cross_channel"
    TECHNICAL = "technical"


class ActionKind(StrEnum):
    SEND_MESSAGE = "send_message"
    REQUEST_SOURCE = "request_source"
    CHANGE_YEAR = "change_year"
    CHANGE_BANK = "change_bank"
    COMPARE_CHANNELS = "compare_channels"
    OPEN_PAGE = "open_page"
    CLICK = "click"
    REFRESH = "refresh"


class FailureCategory(StrEnum):
    WRONG_BANK = "wrong_bank"
    WRONG_YEAR = "wrong_year"
    WRONG_UNIT = "wrong_unit"
    UNSUPPORTED_VALUE = "unsupported_value"
    SOURCE_MISMATCH = "source_mismatch"
    ARITHMETIC_ERROR = "arithmetic_error"
    CONTEXT_LOSS = "context_loss"
    API_ERROR = "api_error"
    FRONTEND_ERROR = "frontend_error"
    DOM_ERROR = "dom_error"
    TIMEOUT = "timeout"
    CHANNEL_DIVERGENCE = "channel_divergence"
    CONTRACT_VIOLATION = "contract_violation"
    PERSONAL_DATA_SCOPE = "personal_data_scope"
    UNSUPPORTED_COMPARISON = "unsupported_comparison"
    UNSUPPORTED_CONVERSION = "unsupported_conversion"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNDETERMINED = "undetermined"


class TestObjective(BaseModel):
    """A measurable property selected for a single test iteration."""

    objective_id: str
    category: TestCategory
    description: str = Field(min_length=3, max_length=500)
    required_properties: list[str] = Field(min_length=1)
    priority: int = Field(default=50, ge=0, le=100)
    rationale: str = Field(min_length=3, max_length=1_000)


class TestCase(BaseModel):
    """A reproducible input plus its expected properties, never a hidden oracle."""

    test_id: str
    title: str = Field(min_length=3, max_length=240)
    category: TestCategory
    channels: list[Channel] = Field(min_length=1)
    input: str = Field(min_length=1, max_length=10_000)
    objective: TestObjective
    bank_id: str | None = None
    reporting_year: int | None = Field(default=None, ge=2000, le=2100)
    metric_id: str | None = None
    conversation_context: dict[str, Any] = Field(default_factory=dict)
    expected_properties: list[str] = Field(min_length=1)
    failure_criteria: list[str] = Field(min_length=1)
    origin: str = "planned"


class GeneratedQuestion(BaseModel):
    """Only the wording proposed by the Generator; all test rules stay local."""

    title: str = Field(min_length=3, max_length=120)
    question: str = Field(min_length=3, max_length=500)


class PlannedAction(BaseModel):
    """One bounded executor instruction chosen by the planner."""

    action_id: str
    objective_id: str
    kind: ActionKind
    channel: Channel
    rationale: str = Field(min_length=3, max_length=1_000)
    question: str | None = Field(default=None, max_length=10_000)
    selector: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=2_000)
    session_id: str | None = None
    parent_step_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class PlannerRationale(BaseModel):
    """Non-authoritative explanation from the Planner; action fields stay local."""

    rationale: str = Field(min_length=3, max_length=300)


class ToolExecutionResult(BaseModel):
    """Raw, normalised output of an API, browser or deterministic tool action."""

    action_id: str
    channel: Channel
    started_at: datetime
    finished_at: datetime
    latency_ms: int = Field(ge=0)
    http_status: int | None = Field(default=None, ge=0, le=599)
    response: dict[str, Any] | None = None
    visible_text: str | None = None
    screenshot_paths: list[str] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class Observation(BaseModel):
    """Read-only state collected before or after one campaign action."""

    observation_id: str
    channel: Channel
    observed_at: datetime
    session_id: str | None = None
    visible_response: str | None = None
    dom_snapshot: str | None = None
    session_state: dict[str, Any] = Field(default_factory=dict)
    frontend_logs: list[str] = Field(default_factory=list)
    backend_logs: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_logs: list[dict[str, Any]] = Field(default_factory=list)
    execution: ToolExecutionResult | None = None
    errors: list[str] = Field(default_factory=list)


class RetrievedEvidence(BaseModel):
    """One source-grounding record returned by the financial evidence layer."""

    document_id: str
    source_path: str
    page_number: int = Field(ge=1)
    chunk_id: str | None = None
    excerpt: str = Field(min_length=1)
    metric_id: str | None = None
    reporting_year: int | None = Field(default=None, ge=2000, le=2100)
    unit_scale: str | None = None
    value: str | None = None
    retrieval_score: float | None = Field(default=None, ge=0)
    evidence_kind: str = "source_excerpt"


class DeterministicCheck(BaseModel):
    """A code-based check; LLMs cannot override this result."""

    check_id: str
    name: str
    passed: bool | None
    severity: str = "error"
    expected: Any = None
    actual: Any = None
    detail: str = ""


class GroundingStatus(StrEnum):
    """Outcome of matching a response against an auto-validated financial fact."""

    VERIFIED = "verified"
    MISSING_EXPECTED_FACT = "missing_expected_fact"
    RESPONSE_MISMATCH = "response_mismatch"
    INCONCLUSIVE = "inconclusive"


class GroundingResult(BaseModel):
    """PDF-backed evidence and comparisons returned by Financial Grounding."""

    test_id: str
    status: GroundingStatus
    expected_bank_id: str | None = None
    expected_reporting_year: int | None = Field(default=None, ge=2000, le=2100)
    expected_metric_id: str | None = None
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    checks: list[DeterministicCheck] = Field(default_factory=list)


class DeterministicValidationResult(BaseModel):
    """Final code-based decision; no LLM may override this result."""

    test_id: str
    verdict: Verdict
    checks: list[DeterministicCheck]
    grounding: GroundingResult | None = None
    failure_categories: list[FailureCategory] = Field(default_factory=list)


class CrossChannelResult(BaseModel):
    """Deterministic comparison of a single question answered by API and Web."""

    test_id: str
    verdict: Verdict
    checks: list[DeterministicCheck]
    failure_categories: list[FailureCategory] = Field(default_factory=list)


class EvaluatorOpinion(BaseModel):
    """Quality opinion returned by Groq; it contains no verdict or source proof."""

    relevance: int = Field(ge=1, le=5)
    factuality: int = Field(ge=1, le=5)
    source_fidelity: int = Field(ge=1, le=5)
    conversation_coherence: int = Field(ge=1, le=5)
    year_respect: int = Field(ge=1, le=5)
    unit_respect: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    format_respect: int = Field(ge=1, le=5)
    failure_category: FailureCategory | None = None
    probable_cause: str | None = Field(default=None, max_length=1_000)
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=3, max_length=2_000)


class CriticOpinion(BaseModel):
    """Bounded follow-up suggestion returned by Groq after an evaluation."""

    next_action_required: bool
    reason: str = Field(min_length=3, max_length=1_000)
    next_objective: TestObjective | None = None
    follow_up_question: str | None = Field(default=None, min_length=3, max_length=1_000)


class EvaluationResult(BaseModel):
    """Structured evaluator verdict supported by evidence and code checks."""

    test_id: str
    verdict: Verdict
    relevance: int = Field(ge=1, le=5)
    factuality: int = Field(ge=1, le=5)
    source_fidelity: int = Field(ge=1, le=5)
    conversation_coherence: int = Field(ge=1, le=5)
    year_respect: int = Field(ge=1, le=5)
    unit_respect: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    format_respect: int = Field(ge=1, le=5)
    failure_category: FailureCategory | None = None
    probable_cause: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    deterministic_checks: list[DeterministicCheck] = Field(default_factory=list)
    rationale: str = Field(min_length=3, max_length=2_000)


class CriticDecision(BaseModel):
    """The bounded decision made after reviewing an evaluation."""

    decision_id: str
    verdict_confirmed: bool
    next_action_required: bool
    create_regression_test: bool
    reason: str = Field(min_length=3, max_length=1_000)
    next_objective: TestObjective | None = None
    follow_up_question: str | None = None
    confidence: float = Field(ge=0, le=1)


class RegressionCase(BaseModel):
    """A confirmed defect recorded as a future reproducible test."""

    regression_id: str
    source_test_id: str
    created_at: datetime
    test_case: TestCase
    failure_category: FailureCategory
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    success_criteria: list[str] = Field(min_length=1)
    duplicate_key: str


class TraceEvent(BaseModel):
    """One chronologically ordered event, suitable for JSON Lines storage."""

    run_id: str
    test_id: str
    trace_id: str
    step_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    channel: Channel
    event_type: str = Field(min_length=3, max_length=100)
    source: str = Field(min_length=2, max_length=100)
    session_id: str | None = None
    parent_step_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class FinalReport(BaseModel):
    """Auditable campaign outcome written as JSON and rendered as Markdown/HTML."""

    run_id: str
    trace_id: str
    started_at: datetime
    finished_at: datetime
    tests: list[EvaluationResult]
    regressions: list[RegressionCase] = Field(default_factory=list)
    groq_call_count: int = Field(default=0, ge=0)
    recommendations: list[str] = Field(default_factory=list)


class ApiPrototypeReport(BaseModel):
    """Minimal vertical-slice report before the evaluator and critic are added."""

    run_id: str
    trace_id: str
    test_id: str
    endpoint: str
    verdict: Verdict
    duration_ms: int = Field(ge=0)
    checks: list[DeterministicCheck]
    grounding: GroundingResult | None = None
    failure_categories: list[FailureCategory] = Field(default_factory=list)
    evaluation: EvaluationResult | None = None
    critic_decision: CriticDecision | None = None
    regression: RegressionCase | None = None
    regression_registry_path: str | None = None
    response: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    trace_path: str
    markdown_path: str | None = None
    html_path: str | None = None
