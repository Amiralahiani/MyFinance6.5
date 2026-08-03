"""First vertical autonomous-QA slice: API action, trace and JSON report."""

from __future__ import annotations

from pathlib import Path

from myfinance_autotest.agents.critic import critique_evaluation
from myfinance_autotest.agents.evaluator import evaluate_response
from myfinance_autotest.agents.observer import observe_execution
from myfinance_autotest.config import AutotestSettings
from myfinance_autotest.executors.api import ApiExecutor
from myfinance_autotest.models import (
    ActionKind,
    ApiPrototypeReport,
    Channel,
    DeterministicCheck,
    PlannedAction,
    TestCase,
    TraceEvent,
)
from myfinance_autotest.observability.storage import JsonlTraceStore
from myfinance_autotest.regressions.registry import (
    RegressionRegistry,
    regression_from_confirmed_defect,
)
from myfinance_autotest.reporting.json_report import write_api_prototype_report
from myfinance_autotest.reporting.rendered_report import write_rendered_api_report
from myfinance_autotest.state import CampaignState, CampaignStep
from myfinance_autotest.tools.groq_client import GroqClient
from myfinance_autotest.validators.deterministic import validate_deterministically


def run_api_prototype(
    test_case: TestCase,
    settings: AutotestSettings,
    *,
    executor: ApiExecutor | None = None,
    groq_client: GroqClient | None = None,
    trace_root: Path,
    report_root: Path,
    regression_root: Path | None = None,
) -> tuple[CampaignState, ApiPrototypeReport, Path]:
    """Run one real API action and persist its evidence before an LLM evaluates it."""
    state = CampaignState.initialise(test_case, settings.limits)
    api_executor = executor or ApiExecutor(settings.endpoints.api_base_url)
    owns_executor = executor is None
    store = JsonlTraceStore(trace_root)
    action = PlannedAction(
        action_id=f"{test_case.test_id}-ACTION-001",
        objective_id=test_case.objective.objective_id,
        kind=ActionKind.SEND_MESSAGE,
        channel=Channel.API,
        question=test_case.input,
        rationale="Exécuter le cas de test sur l’API conversationnelle réelle.",
        parameters={"context": test_case.conversation_context},
    )
    store.append(
        TraceEvent(
            run_id=state.run_id,
            test_id=test_case.test_id,
            trace_id=state.trace_id,
            step_id="STEP-001",
            channel=Channel.API,
            event_type="action_planned",
            source="orchestrator",
            data={"action": action.model_dump(mode="json")},
        )
    )
    try:
        execution = api_executor.execute(action)
    finally:
        if owns_executor:
            api_executor.close()
    observation = observe_execution("OBS-001", execution)
    technical_checks = [
        DeterministicCheck(
            check_id="CHECK-HTTP-200",
            name="http_status_is_success",
            passed=execution.http_status == 200,
            expected=200,
            actual=execution.http_status,
            detail="L’API conversationnelle doit retourner HTTP 200.",
        ),
        DeterministicCheck(
            check_id="CHECK-LATENCY",
            name="latency_within_global_limit",
            passed=execution.latency_ms <= settings.limits.global_test_timeout_seconds * 1_000,
            expected=f"<= {settings.limits.global_test_timeout_seconds * 1_000} ms",
            actual=execution.latency_ms,
            detail="La latence doit rester sous le timeout global de campagne.",
        ),
    ]
    state.record_step(
        CampaignStep(
            step_id="STEP-001",
            sequence=1,
            objective=test_case.objective,
            action=action,
            observation=observation,
            execution=execution,
            deterministic_checks=technical_checks,
        )
    )
    trace_path = store.append(
        TraceEvent(
            run_id=state.run_id,
            test_id=test_case.test_id,
            trace_id=state.trace_id,
            step_id="STEP-001",
            channel=Channel.API,
            event_type="api_execution",
            source="api_executor",
            data={
                "execution": execution.model_dump(mode="json"),
                "technical_checks": [item.model_dump() for item in technical_checks],
            },
        )
    )
    validation = validate_deterministically(test_case, execution, technical_checks)
    state.steps[-1].evidence = validation.grounding.evidence if validation.grounding else []
    state.steps[-1].deterministic_checks = validation.checks
    store.append(
        TraceEvent(
            run_id=state.run_id,
            test_id=test_case.test_id,
            trace_id=state.trace_id,
            step_id="STEP-001",
            channel=Channel.API,
            event_type="deterministic_validation",
            source="deterministic_validator",
            data=validation.model_dump(mode="json"),
        )
    )
    evaluation = None
    critic_decision = None
    regression = None
    regression_registry_path = None
    if groq_client is not None:
        evaluation, evaluator_call = evaluate_response(
            test_case,
            execution,
            validation,
            client=groq_client,
            campaign=state,
        )
        state.steps[-1].evaluation = evaluation
        store.append(
            TraceEvent(
                run_id=state.run_id,
                test_id=test_case.test_id,
                trace_id=state.trace_id,
                step_id="STEP-001",
                channel=Channel.API,
                event_type="quality_evaluation",
                source="groq_evaluator",
                data={
                    "evaluation": evaluation.model_dump(mode="json"),
                    "provider": evaluator_call.trace_data(),
                },
            )
        )
        candidate = regression_from_confirmed_defect(test_case, validation, critic_decision)
        if candidate is not None:
            registration = RegressionRegistry(regression_root or report_root.parent / "regressions").register(candidate)
            regression = registration.regression
            regression_registry_path = str(registration.path)
            store.append(
                TraceEvent(
                    run_id=state.run_id,
                    test_id=test_case.test_id,
                    trace_id=state.trace_id,
                    step_id="STEP-001",
                    channel=Channel.API,
                    event_type="regression_registered",
                    source="regression_registry",
                    data={
                        "regression": regression.model_dump(mode="json"),
                        "created": registration.created,
                        "registry_path": str(registration.path),
                    },
                )
            )
        critic_decision, critic_call = critique_evaluation(
            test_case,
            evaluation,
            validation,
            client=groq_client,
            campaign=state,
        )
        state.steps[-1].critic_decision = critic_decision
        state.evaluate_stop_condition()
        store.append(
            TraceEvent(
                run_id=state.run_id,
                test_id=test_case.test_id,
                trace_id=state.trace_id,
                step_id="STEP-001",
                channel=Channel.API,
                event_type="critic_decision",
                source="groq_critic",
                data={
                    "critic_decision": critic_decision.model_dump(mode="json"),
                    "provider": critic_call.trace_data(),
                    "stop_reason": state.stop_reason,
                },
            )
        )
    report = ApiPrototypeReport(
        run_id=state.run_id,
        trace_id=state.trace_id,
        test_id=test_case.test_id,
        endpoint=f"{api_executor.base_url}/api/conversation/answer",
        verdict=validation.verdict,
        duration_ms=execution.latency_ms,
        checks=validation.checks,
        grounding=validation.grounding,
        failure_categories=validation.failure_categories,
        evaluation=evaluation,
        critic_decision=critic_decision,
        regression=regression,
        regression_registry_path=regression_registry_path,
        response=execution.response,
        errors=execution.errors,
        trace_path=str(trace_path),
    )
    markdown_path, html_path = write_rendered_api_report(report, report_root)
    report = report.model_copy(update={"markdown_path": str(markdown_path), "html_path": str(html_path)})
    report_path = write_api_prototype_report(report, report_root)
    return state, report, report_path
