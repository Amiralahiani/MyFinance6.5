"""Vertical-slice tests for API execution, observation, JSONL trace and report."""

from __future__ import annotations

import json

import httpx
from myfinance_agent_docs.facts import auto_validated_fact
from myfinance_autotest import models
from myfinance_autotest.campaign import run_api_prototype
from myfinance_autotest.config import load_settings
from myfinance_autotest.executors.api import ApiExecutor
from myfinance_autotest.observability.storage import JsonlTraceStore


def _case() -> models.TestCase:
    objective = models.TestObjective(
        objective_id="OBJ-API-001",
        category=models.TestCategory.FINANCIAL_FACT,
        description="Vérifier que le chatbot répond via l’API.",
        required_properties=["http_success"],
        rationale="Le premier prototype doit produire une réponse traçable.",
    )
    return models.TestCase(
        test_id="TEST-API-001",
        title="Valeur PNB BIAT 2025",
        category=models.TestCategory.FINANCIAL_FACT,
        channels=[models.Channel.API],
        input="Quel est le PNB de BIAT en 2025 ?",
        objective=objective,
        expected_properties=["http_success"],
        failure_criteria=["api_error"],
    )


def test_api_prototype_records_the_real_contract_shape_in_trace_and_report(tmp_path) -> None:
    fact = auto_validated_fact("biat", 2025, "net_banking_income")
    assert fact is not None

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/conversation/answer"
        assert json.loads(request.content) == {"message": "Quel est le PNB de BIAT en 2025 ?", "context": {}}
        return httpx.Response(
            200,
            json={
                "type": "numeric",
                "metric_id": fact.metric_id,
                "value": str(fact.value),
                "currency": fact.currency,
                "unit_scale": fact.unit_scale,
                "reporting_year": fact.reporting_year,
                "source_document": fact.source_path,
                "page_number": fact.page_number,
                "source_excerpt": fact.source_excerpt,
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://target")
    executor = ApiExecutor("http://target", client=client)
    state, report, report_path = run_api_prototype(
        _case(),
        load_settings(environment={}),
        executor=executor,
        trace_root=tmp_path / "traces",
        report_root=tmp_path / "reports",
    )

    assert report.verdict is models.Verdict.PASS
    assert report.response["value"] == str(fact.value)
    assert report.grounding is not None
    assert report.grounding.status is models.GroundingStatus.VERIFIED
    assert report_path.exists()
    events = JsonlTraceStore(tmp_path / "traces").read(state.run_id, state.trace_id)
    assert [event.event_type for event in events] == [
        "action_planned",
        "api_execution",
        "deterministic_validation",
    ]
    assert events[-2].data["execution"]["http_status"] == 200
    assert events[-1].data["verdict"] == "pass"


def test_api_prototype_reports_an_http_failure_without_hiding_it(tmp_path) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, json={"detail": "unavailable"})),
        base_url="http://target",
    )
    _, report, _ = run_api_prototype(
        _case(),
        load_settings(environment={}),
        executor=ApiExecutor("http://target", client=client),
        trace_root=tmp_path / "traces",
        report_root=tmp_path / "reports",
    )

    assert report.verdict is models.Verdict.FAIL
    assert report.errors == ["HTTP 503"]


def test_api_executor_retries_one_transient_transport_failure() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("temporary delay", request=request)
        return httpx.Response(200, json={"type": "clarification", "message": "Recovered."})

    action = models.PlannedAction(
        action_id="ACTION-RETRY-001",
        objective_id="OBJ-API-001",
        kind=models.ActionKind.SEND_MESSAGE,
        channel=models.Channel.API,
        rationale="Confirm that one transient transport failure is retried.",
        question="Please clarify the metric.",
    )
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://target")
    result = ApiExecutor("http://target", client=client, max_retries=1).execute(action)

    assert attempts == 2
    assert result.http_status == 200
    assert result.response == {"type": "clarification", "message": "Recovered."}
    assert result.errors == []
