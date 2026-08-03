"""Explicit, serialisable campaign state and deterministic stopping rules."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from myfinance_autotest.config import CampaignLimits
from myfinance_autotest.models import (
    CriticDecision,
    DeterministicCheck,
    EvaluationResult,
    Observation,
    PlannedAction,
    RetrievedEvidence,
    TestCase,
    TestObjective,
    ToolExecutionResult,
)


class CampaignStep(BaseModel):
    """All observable outcomes of one iteration in the autonomous loop."""

    step_id: str
    sequence: int = Field(ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    objective: TestObjective
    action: PlannedAction
    observation: Observation | None = None
    execution: ToolExecutionResult | None = None
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    deterministic_checks: list[DeterministicCheck] = Field(default_factory=list)
    evaluation: EvaluationResult | None = None
    critic_decision: CriticDecision | None = None

    def action_fingerprint(self) -> str:
        """Identify equivalent actions to protect the campaign from loops."""
        return "|".join(
            [
                self.action.channel,
                self.action.kind,
                self.action.question or "",
                self.action.selector or "",
                self.action.url or "",
            ]
        )


class CampaignState(BaseModel):
    """The only mutable state owned by the orchestrator during one campaign."""

    run_id: str
    trace_id: str
    test_case: TestCase
    limits: CampaignLimits
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    llm_call_count: int = Field(default=0, ge=0)
    steps: list[CampaignStep] = Field(default_factory=list)
    stop_reason: str | None = None

    @classmethod
    def initialise(cls, test_case: TestCase, limits: CampaignLimits) -> CampaignState:
        """Create opaque identifiers once, at the campaign boundary."""
        run_id = f"RUN-{uuid4().hex[:12]}"
        return cls(
            run_id=run_id,
            trace_id=f"TRACE-{uuid4().hex[:12]}",
            test_case=test_case,
            limits=limits,
        )

    def record_step(self, step: CampaignStep) -> None:
        """Append a complete step while enforcing sequencing and unique identifiers."""
        if self.stop_reason:
            raise RuntimeError(f"Campaign already stopped: {self.stop_reason}")
        if step.sequence != len(self.steps) + 1:
            raise ValueError("Campaign step sequence must increase by exactly one.")
        if any(existing.step_id == step.step_id for existing in self.steps):
            raise ValueError(f"Duplicate campaign step id: {step.step_id}")
        self.steps.append(step)

    def register_llm_call(self) -> None:
        """Count calls before sending them so configured budgets cannot be exceeded."""
        if self.llm_call_count >= self.limits.max_llm_calls_per_test:
            raise RuntimeError("The configured LLM-call budget has been exhausted.")
        self.llm_call_count += 1

    def _repeated_action_count(self) -> int:
        if not self.steps:
            return 0
        fingerprint = self.steps[-1].action_fingerprint()
        return sum(step.action_fingerprint() == fingerprint for step in self.steps)

    def evaluate_stop_condition(self, *, now: datetime | None = None) -> str | None:
        """Return a deterministic stop reason, or ``None`` when investigation may continue."""
        timestamp = now or datetime.now(UTC)
        if self.stop_reason:
            return self.stop_reason
        if self.steps:
            last_decision = self.steps[-1].critic_decision
            if last_decision and last_decision.verdict_confirmed and not last_decision.next_action_required:
                self.stop_reason = "verdict_confirmed"
                return self.stop_reason
        if len(self.steps) >= self.limits.max_agent_steps:
            self.stop_reason = "max_agent_steps_reached"
        elif self.llm_call_count >= self.limits.max_llm_calls_per_test:
            self.stop_reason = "max_llm_calls_reached"
        elif (timestamp - self.started_at).total_seconds() >= self.limits.global_test_timeout_seconds:
            self.stop_reason = "global_timeout_reached"
        elif self._repeated_action_count() > self.limits.max_repeated_actions:
            self.stop_reason = "repeated_action_limit_reached"
        return self.stop_reason
