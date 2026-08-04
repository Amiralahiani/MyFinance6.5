"""Persistent API and SSE feed for the MyFinance Agentic Testing application."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from myfinance_autotest import models
from myfinance_autotest.agents.generator import generate_test_case
from myfinance_autotest.agents.planner import plan_api_action
from myfinance_autotest.campaign import run_api_prototype
from myfinance_autotest.campaign_runner import run_scenario_batch, write_campaign_report
from myfinance_autotest.config import EndpointConfig, load_settings
from myfinance_autotest.executors.api import ApiExecutor
from myfinance_autotest.executors.web import WebExecutor
from myfinance_autotest.scenarios.exploration import bind_generated_scenario, exploration_charters
from myfinance_autotest.scenarios.library import ScenarioLibrary, build_scenario_library
from myfinance_autotest.state import CampaignState
from myfinance_autotest.tools.groq_client import GroqClient
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATABASE_PATH = Path(os.environ.get("TESTING_DATABASE_PATH", PROJECT_ROOT / "data" / "autotest" / "testing.sqlite"))
CHAT_API_URL = os.environ.get("CHAT_API_URL", "http://127.0.0.1:8000")
CHAT_WEB_URL = os.environ.get("CHAT_WEB_URL", "http://127.0.0.1:3000")
PLAYWRIGHT_REPORT_PATH = PROJECT_ROOT / "chat" / "web" / "test-results" / "playwright-results.json"
PLAYWRIGHT_WORKDIR = PROJECT_ROOT / "chat" / "web"
CAMPAIGN_REPORT_ROOT = PROJECT_ROOT / "data" / "autotest" / "campaigns"
app = FastAPI(title="MyFinance Agentic Testing", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class CreateTestRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10_000)
    answer: dict | None = None
    conversation_id: str | None = None
    context: dict = Field(default_factory=dict)
    sources: list[dict] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    model: str | None = None
    origin: str = "manual"


class StartCatalogCampaignRequest(BaseModel):
    include_web: bool = True
    with_groq: bool = True
    max_scenarios: int | None = Field(default=None, ge=1, le=500)
    scenario_profile: str = Field(default="exploration", pattern=r"^(catalog|behavior|exploration)$")


def _connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tests (
          id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, payload TEXT NOT NULL, result TEXT, error TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, test_id TEXT NOT NULL,
          created_at TEXT NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS campaigns (
          id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, configuration TEXT NOT NULL, result TEXT, error TEXT
        );
        CREATE TABLE IF NOT EXISTS campaign_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL,
          created_at TEXT NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS visual_checks (
          id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, result TEXT, error TEXT
        );
        CREATE TABLE IF NOT EXISTS visual_check_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, visual_check_id TEXT NOT NULL,
          created_at TEXT NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL
        );
        """
    )
    return connection


def _event(test_id: str, event_type: str, data: dict) -> None:
    with _connection() as connection:
        connection.execute(
            "INSERT INTO events(test_id, created_at, type, data) VALUES (?, ?, ?, ?)",
            (test_id, datetime.now(UTC).isoformat(), event_type, json.dumps(data, ensure_ascii=False)),
        )


def _read_test(test_id: str) -> dict:
    with _connection() as connection:
        row = connection.execute("SELECT * FROM tests WHERE id = ?", (test_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Test introuvable.")
    return {
        "id": row["id"], "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "payload": json.loads(row["payload"]), "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"],
    }


def _campaign_event(campaign_id: str, event_type: str, data: dict) -> None:
    with _connection() as connection:
        connection.execute(
            "INSERT INTO campaign_events(campaign_id, created_at, type, data) VALUES (?, ?, ?, ?)",
            (campaign_id, datetime.now(UTC).isoformat(), event_type, json.dumps(data, ensure_ascii=False)),
        )


def _read_campaign(campaign_id: str) -> dict:
    with _connection() as connection:
        row = connection.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        events = connection.execute("SELECT * FROM campaign_events WHERE campaign_id = ? ORDER BY id", (campaign_id,)).fetchall()
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return {
        "id": row["id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "configuration": json.loads(row["configuration"]),
        "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"],
        "events": [
            {"id": item["id"], "created_at": item["created_at"], "type": item["type"], **json.loads(item["data"])}
            for item in events
        ],
    }


def _visual_check_event(visual_check_id: str, event_type: str, data: dict) -> None:
    with _connection() as connection:
        connection.execute(
            "INSERT INTO visual_check_events(visual_check_id, created_at, type, data) VALUES (?, ?, ?, ?)",
            (visual_check_id, datetime.now(UTC).isoformat(), event_type, json.dumps(data, ensure_ascii=False)),
        )


def _read_visual_check(visual_check_id: str) -> dict:
    with _connection() as connection:
        row = connection.execute("SELECT * FROM visual_checks WHERE id = ?", (visual_check_id,)).fetchone()
        events = connection.execute(
            "SELECT * FROM visual_check_events WHERE visual_check_id = ? ORDER BY id", (visual_check_id,)
        ).fetchall()
    if row is None:
        raise HTTPException(status_code=404, detail="Contrôle visuel introuvable.")
    return {
        "id": row["id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"],
        "events": [
            {"id": event["id"], "created_at": event["created_at"], "type": event["type"], **json.loads(event["data"])}
            for event in events
        ],
    }


def _latest_visual_check() -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT id FROM visual_checks ORDER BY created_at DESC LIMIT 1").fetchone()
    return _read_visual_check(row["id"]) if row else None


def _update_visual_check(visual_check_id: str, *, status: str, result: dict | None = None, error: str | None = None) -> None:
    with _connection() as connection:
        connection.execute(
            "UPDATE visual_checks SET status=?, updated_at=?, result=?, error=? WHERE id=?",
            (status, datetime.now(UTC).isoformat(), json.dumps(result, ensure_ascii=False) if result else None, error, visual_check_id),
        )


def _canonical_question(question: str) -> str:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFD", question.lower())
        if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _previous_exploration_questions(limit: int = 160) -> list[str]:
    """Return accepted Generator questions from prior campaigns, newest first."""

    with _connection() as connection:
        rows = connection.execute(
            "SELECT data FROM campaign_events WHERE type='agent_output' ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    questions: list[str] = []
    for row in rows:
        payload = json.loads(row["data"])
        question = payload.get("question")
        if payload.get("stage") == "generator" and payload.get("status") == "completed" and isinstance(question, str):
            questions.append(question)
    return questions


def _is_new_exploration_question(question: str, previous_questions: list[str]) -> bool:
    """Reject exact and near duplicates independently of the LLM instruction."""

    candidate = _canonical_question(question)
    if not candidate:
        return False
    candidate_terms = set(candidate.split())
    for previous in previous_questions:
        normalized_previous = _canonical_question(previous)
        if not normalized_previous:
            continue
        sequence_similarity = SequenceMatcher(a=candidate, b=normalized_previous).ratio()
        previous_terms = set(normalized_previous.split())
        union = candidate_terms | previous_terms
        term_similarity = len(candidate_terms & previous_terms) / len(union) if union else 1.0
        if sequence_similarity >= 0.86 or term_similarity >= 0.82:
            return False
    return True


def _groq_failure_message(error: str | None) -> str:
    """Turn a normalised provider error into an actionable, secret-free message."""

    if error and "BadRequestError" in error:
        return "Groq rejected the request. The provider’s safe detail is displayed under the relevant attempt."
    if error and "RateLimitError" in error:
        return "Groq is temporarily rate-limiting requests for this key. Wait, then restart the campaign."
    if error and "AuthenticationError" in error:
        return "Groq rejected the configured key. Check GROQ_API_KEY in the Testing service terminal."
    if error and "PermissionDeniedError" in error:
        return "This Groq key is not authorised to use the configured model."
    if error and "NotFoundError" in error:
        return "The configured Groq model was not found or is unavailable for this key."
    return "Groq is unavailable for scenario generation. Try again after checking the service and its configuration."


def _case(test_id: str, payload: dict) -> models.TestCase:
    question = payload["question"]
    is_greeting = bool(re.fullmatch(r"\s*(?:bonjour|bonsoir|salut|coucou)[!.\s]*", question, flags=re.IGNORECASE))
    category = models.TestCategory.CONVERSATION if is_greeting else models.TestCategory.FINANCIAL_FACT
    objective = models.TestObjective(
        objective_id=f"OBJ-{test_id}", category=category,
        description="Check a conversational response without requiring financial evidence." if is_greeting else "Replay a chatbot response with deterministic checks and PDF evidence.",
        required_properties=["http_success"] if is_greeting else ["http_success", "source_fidelity"],
        rationale="The test originates from a conversation or an explicitly submitted input.",
    )
    return models.TestCase(
        test_id=test_id, title=question[:160], category=category,
        channels=[models.Channel.API], input=question, objective=objective,
        conversation_context=payload.get("context", {}), expected_properties=["http_success"] if is_greeting else ["http_success", "source_fidelity"],
        failure_criteria=["api_error"] if is_greeting else ["api_error", "unsupported_value", "source_mismatch"], origin=payload.get("origin", "manual"),
    )


def _playwright_specs(suites: list[dict]) -> list[dict]:
    specs: list[dict] = []
    for suite in suites:
        specs.extend(suite.get("specs", []))
        specs.extend(_playwright_specs(suite.get("suites", [])))
    return specs


def _web_coverage() -> dict:
    """Read the actual Playwright JSON report; never fabricate a Web result."""
    if not PLAYWRIGHT_REPORT_PATH.exists():
        return {"available": False, "summary": {"total": 0, "passed": 0, "failed": 0}, "tests": []}
    payload = json.loads(PLAYWRIGHT_REPORT_PATH.read_text(encoding="utf-8"))
    tests: list[dict] = []
    for spec in _playwright_specs(payload.get("suites", [])):
        results = [result for test in spec.get("tests", []) for result in test.get("results", [])]
        if not results:
            continue
        latest = results[-1]
        tests.append({
            "title": spec.get("title", ""),
            "status": latest.get("status", "unknown"),
            "duration_ms": latest.get("duration"),
        })
    return {
        "available": True,
        "generated_at": payload.get("stats", {}).get("startTime"),
        "summary": {"total": len(tests), "passed": sum(test["status"] == "passed" for test in tests), "failed": sum(test["status"] != "passed" for test in tests)},
        "tests": tests,
    }


def _run_visual_check(visual_check_id: str) -> None:
    """Run the fixed Playwright suite and publish safe progress lines over SSE."""

    progress: dict[str, int | None] = {"total": None, "completed": 0, "passed": 0, "failed": 0}
    seen_tests: set[str] = set()
    _update_visual_check(visual_check_id, status="running", result={"progress": progress})
    _visual_check_event(visual_check_id, "visual_started", {
        "status": "running",
        "message": "Le navigateur automatisé démarre. Les parcours apparaîtront ci-dessous.",
        "progress": progress,
    })
    try:
        command = ["npm.cmd" if os.name == "nt" else "npm", "run", "test:e2e"]
        environment = os.environ.copy()
        # Playwright starts its own orchestrator through ``python -m uv``.  The
        # Testing API itself often runs from .venv, where uv is intentionally
        # absent; its base interpreter is the one that owns uv on this setup.
        base_python = Path(sys.base_prefix) / ("python.exe" if os.name == "nt" else "bin/python")
        environment.setdefault("MYFINANCE_UV_PYTHON", str(base_python))
        # A run explicitly launched from the Testing page is meant to be observed.
        environment["MYFINANCE_PLAYWRIGHT_VISIBLE"] = "1"
        process = subprocess.Popen(
            command,
            cwd=PLAYWRIGHT_WORKDIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            total_match = re.search(r"Running\s+(\d+)\s+tests?", line, flags=re.IGNORECASE)
            if total_match:
                progress["total"] = int(total_match.group(1))
            result_match = re.search(r"([✓✘×])\s+\d+.*?›\s*(.+)$", line)
            if result_match:
                marker, title = result_match.groups()
                key = title.strip()
                if key not in seen_tests:
                    seen_tests.add(key)
                    progress["completed"] = int(progress["completed"] or 0) + 1
                    if marker == "✓":
                        progress["passed"] = int(progress["passed"] or 0) + 1
                    else:
                        progress["failed"] = int(progress["failed"] or 0) + 1
            snapshot = {"progress": progress}
            _update_visual_check(visual_check_id, status="running", result=snapshot)
            _visual_check_event(visual_check_id, "visual_output", {"line": line, **snapshot})
        exit_code = process.wait()
        coverage = _web_coverage()
        summary = coverage.get("summary", {})
        final_progress = {
            "total": summary.get("total", progress["total"]),
            "completed": summary.get("total", progress["completed"]),
            "passed": summary.get("passed", progress["passed"]),
            "failed": summary.get("failed", progress["failed"]),
        }
        result = {"progress": final_progress, "coverage": coverage}
        status = "completed" if exit_code == 0 and coverage.get("available") else "failed"
        error = None if status == "completed" else "The Playwright check failed. See the log below."
        _update_visual_check(visual_check_id, status=status, result=result, error=error)
        _visual_check_event(visual_check_id, "visual_completed", {
            "status": status,
            "exit_code": exit_code,
            "message": "Visual check completed." if status == "completed" else error,
            **result,
        })
    # Background work must always publish a terminal status, including an
    # unexpected Playwright process failure.
    except Exception as error:  # noqa: BLE001
        message = f"Impossible de démarrer Playwright : {type(error).__name__}"
        _update_visual_check(visual_check_id, status="technical_error", result={"progress": progress}, error=message)
        _visual_check_event(visual_check_id, "visual_completed", {
            "status": "technical_error", "message": message, "progress": progress,
        })


def _expected_description(scenario: models.TestCase) -> str:
    if scenario.origin == "catalog_auto_validated_fact":
        return "Le chiffre, l’exercice, l’unité et la preuve PDF doivent correspondre au fait auto-validé."
    if scenario.origin == "catalog_missing_auto_validated_fact":
        return "Le Chat doit signaler l’absence de donnée validée, sans inventer de chiffre."
    if scenario.category is models.TestCategory.CROSS_CHANNEL:
        return "L’API et le Web doivent afficher la même valeur et la même preuve PDF."
    labels = {
        "response_type:clarification": "Demander une précision utile.",
        "response_type:document": "Retourner une analyse documentaire.",
        "response_type:courtesy": "Répondre avec un accueil conversationnel.",
        "no_numeric_value": "Ne proposer aucun chiffre.",
        "evidence_present": "Présenter au moins une preuve du rapport.",
        "message_contains:année": "Indiquer que l’année manque.",
        "message_contains:indicateur financier": "Indiquer que l’indicateur est inconnu.",
        "visible_contains:prêt à analyser": "Afficher le message d’accueil dans l’interface Web.",
    }
    return " ".join(labels.get(item, item.replace("_", " ")) for item in scenario.expected_properties)
def _run(test_id: str) -> None:
    payload = _read_test(test_id)["payload"]
    now = datetime.now(UTC).isoformat()
    with _connection() as connection:
        connection.execute("UPDATE tests SET status=?, updated_at=? WHERE id=?", ("running", now, test_id))
    _event(test_id, "execution_started", {"step": "observation"})
    try:
        settings = load_settings().model_copy(update={"endpoints": EndpointConfig(api_base_url=CHAT_API_URL, web_base_url="http://127.0.0.1:3000")})
        _, report, report_path = run_api_prototype(
            _case(test_id, payload), settings, executor=ApiExecutor(CHAT_API_URL),
            trace_root=PROJECT_ROOT / "data" / "autotest" / "traces", report_root=PROJECT_ROOT / "data" / "autotest" / "reports",
        )
        result = report.model_dump(mode="json") | {"report_path": str(report_path)}
        status = "passed" if report.verdict is models.Verdict.PASS else "inconclusive" if report.verdict is models.Verdict.INCONCLUSIVE else "failed"
        with _connection() as connection:
            connection.execute("UPDATE tests SET status=?, updated_at=?, result=?, error=NULL WHERE id=?", (status, datetime.now(UTC).isoformat(), json.dumps(result, ensure_ascii=False), test_id))
        _event(test_id, "report_ready", {"step": "report", "status": status, "result": result})
    # A background API test must be persisted as a technical failure rather
    # than leaving its visible status indefinitely at "running".
    except Exception as error:  # noqa: BLE001
        with _connection() as connection:
            connection.execute("UPDATE tests SET status=?, updated_at=?, error=? WHERE id=?", ("technical_error", datetime.now(UTC).isoformat(), type(error).__name__, test_id))
        _event(test_id, "technical_error", {"error": type(error).__name__})


def _run_catalog_campaign(campaign_id: str) -> None:
    """Run the complete reproducible catalogue without manual scenario entry."""
    campaign = _read_campaign(campaign_id)
    configuration = campaign["configuration"]
    with _connection() as connection:
        connection.execute(
            "UPDATE campaigns SET status=?, updated_at=?, error=NULL WHERE id=?",
            ("running", datetime.now(UTC).isoformat(), campaign_id),
        )
    active_stage = "generator"
    try:
        settings = load_settings().model_copy(update={
            "endpoints": EndpointConfig(api_base_url=CHAT_API_URL, web_base_url=CHAT_WEB_URL),
        })
        groq_enabled = bool(configuration["with_groq"] and settings.groq_api_key)
        groq_client = GroqClient(settings) if groq_enabled else None
        planned_actions: dict[str, models.PlannedAction] = {}
        generation_groq_call_count = 0
        if configuration["scenario_profile"] == "exploration":
            if not groq_enabled or groq_client is None:
                raise RuntimeError(
                    f"The exploratory campaign requires {settings.groq.api_key_environment} in the Testing service environment."
                )
            charters = exploration_charters()
            if configuration["max_scenarios"] is not None:
                charters = charters[:configuration["max_scenarios"]]
            known_questions = _previous_exploration_questions()
            _campaign_event(campaign_id, "stage_update", {
                "stage": "generator", "status": "running", "title": "AI Generator: searching for risk scenarios",
                "risk_charters": len(charters), "previous_questions": len(known_questions),
                "policy": "The model generates questions; safety contracts remain defined locally. Duplicates and rejections are replaced within a strict limit.",
            })
            target_scenarios = len(charters)
            max_generation_attempts = target_scenarios * 3
            generated_scenarios: list[models.TestCase] = []
            selected: list[models.TestCase] = []
            pending_charters = list(charters)
            generation_attempts = 0
            planner_rejections = 0
            _campaign_event(campaign_id, "stage_update", {
                "stage": "planner", "status": "running", "title": "AI Planner: checking authorised actions",
                "target_scenarios": target_scenarios,
            })
            while (
                pending_charters
                and len(selected) < target_scenarios
                and generation_attempts < max_generation_attempts
            ):
                charter = pending_charters.pop(0)
                generation_attempts += 1
                state = CampaignState.initialise(charter, settings.limits)
                generated, metadata = generate_test_case(
                    charter, allowed_channels={models.Channel.API}, client=groq_client, campaign=state,
                    excluded_questions=known_questions,
                )
                generation_groq_call_count += metadata.attempts
                candidate = bind_generated_scenario(charter, generated, generation_attempts) if generated is not None else None
                is_new = candidate is not None and _is_new_exploration_question(candidate.input, known_questions)
                scenario = candidate if is_new else None
                if scenario is not None:
                    known_questions.append(scenario.input)
                    generated_scenarios.append(scenario)
                    generation_status = "completed"
                elif metadata.status == "failed" and (metadata.error or "").startswith("Groq request failed:"):
                    generation_status = "provider_error"
                elif metadata.status == "failed" and "budget" in (metadata.error or "").lower():
                    generation_status = "budget_exhausted"
                elif metadata.status == "failed":
                    generation_status = "invalid_output"
                elif candidate is not None:
                    generation_status = "duplicate"
                else:
                    generation_status = "rejected"
                _campaign_event(campaign_id, "agent_output", {
                    "stage": "generator", "status": generation_status,
                    "charter": charter.test_id, "scenario_id": scenario.test_id if scenario else None,
                    "question": candidate.input if candidate else None, "attempt": generation_attempts,
                    "provider": metadata.trace_data(),
                })
                if metadata.status == "failed" and (metadata.error or "").startswith("Groq request failed:"):
                    raise RuntimeError(_groq_failure_message(metadata.error))
                if scenario is None:
                    pending_charters.append(charter)
                    continue

                action, planner_metadata = plan_api_action(scenario, client=groq_client, campaign=state)
                generation_groq_call_count += planner_metadata.attempts
                _campaign_event(campaign_id, "agent_output", {
                    "stage": "planner", "status": "fallback_local" if planner_metadata.status == "fallback_local" else "completed" if action else "rejected",
                    "scenario_id": scenario.test_id, "question": scenario.input,
                    "provider": planner_metadata.trace_data(),
                })
                if action is not None:
                    planned_actions[scenario.test_id] = action
                    selected.append(scenario)
                else:
                    planner_rejections += 1
                    pending_charters.append(charter)
            if not generated_scenarios:
                raise RuntimeError("Groq produced no usable scenario after schema validation.")
            _campaign_event(campaign_id, "stage_update", {
                "stage": "generator", "status": "completed", "title": "AI-generated exploratory scenarios",
                "generated_scenarios": len(generated_scenarios), "target_scenarios": target_scenarios,
                "risk_charters": len(charters), "generation_attempts": generation_attempts,
                "replacement_attempts": max(0, generation_attempts - target_scenarios),
                "target_reached": len(selected) == target_scenarios,
                "replacement_limit_reached": (
                    len(selected) < target_scenarios and generation_attempts >= max_generation_attempts
                ),
                "previous_questions": len(known_questions) - len(generated_scenarios), "groq_calls": generation_groq_call_count,
            })
            active_stage = "planner"
            if not selected:
                raise RuntimeError("The AI Planner did not authorise any runnable action.")
            library = ScenarioLibrary(
                report_count=0, auto_validated_fact_scenario_count=0, cross_channel_scenario_count=0,
                missing_fact_scenario_count=0, behavior_scenario_count=len(selected), coverage=[], scenarios=selected,
            )
            _campaign_event(campaign_id, "stage_update", {
                "stage": "planner", "status": "completed", "title": "Exploratory actions planned",
                "selected_scenarios": len(selected), "api_scenarios": len(selected), "web_scenarios": 0,
                "target_scenarios": target_scenarios, "planner_rejections": planner_rejections,
                "replacement_limit_reached": len(selected) < target_scenarios,
                "policy": "The Planner can authorise only a message to the local Chat API; rejections trigger replacement generation within the set limit.",
            })
        else:
            library = build_scenario_library()
            selected = (
                [scenario for scenario in library.scenarios if scenario.origin == "catalog_behavior_contract"]
                if configuration["scenario_profile"] == "behavior"
                else list(library.scenarios)
            )
            if not configuration["include_web"]:
                selected = [scenario for scenario in selected if models.Channel.WEB not in scenario.channels]
            if configuration["max_scenarios"] is not None:
                selected = selected[:configuration["max_scenarios"]]
            _campaign_event(campaign_id, "stage_update", {
                "stage": "generator", "status": "completed", "title": "Deterministic catalogue generated",
                "report_count": library.report_count, "scenario_count": len(library.scenarios),
                "auto_validated_fact_scenarios": library.auto_validated_fact_scenario_count,
                "missing_fact_scenarios": library.missing_fact_scenario_count,
                "cross_channel_scenarios": library.cross_channel_scenario_count,
            })
            _campaign_event(campaign_id, "stage_update", {
                "stage": "planner", "status": "completed", "title": "Bounded execution plan",
                "selected_scenarios": len(selected), "api_scenarios": len(selected),
                "web_scenarios": sum(scenario.category is models.TestCategory.CROSS_CHANNEL for scenario in selected),
                "include_web": configuration["include_web"],
                "policy": "Questions, channels and objectives come only from the validated catalogue.",
            })
        if configuration["with_groq"] and not groq_enabled:
            _campaign_event(campaign_id, "stage_update", {
                "stage": "critic", "status": "skipped", "title": "Critic SLM not configured",
                "reason": f"{settings.groq.api_key_environment} is missing: deterministic checks still run.",
            })
        primary_selected = list(selected)
        counts = {verdict.value: 0 for verdict in models.Verdict}
        primary_counts = {verdict.value: 0 for verdict in models.Verdict}
        confirmation_counts = {verdict.value: 0 for verdict in models.Verdict}
        confirmation_requests: list[tuple[models.TestCase, str]] = []
        quality_fallbacks = {
            "initial": {"evaluator": 0, "critic": 0},
            "confirmation": {"evaluator": 0, "critic": 0},
        }

        def record_execution(passage: str):
            """Publish the Chat response before any slower Groq quality review."""

            executor_stage = "executor" if passage == "initial" else "executor_confirmation"

            def callback(index: int, total: int, scenario: models.TestCase, execution: dict) -> None:
                _campaign_event(campaign_id, "stage_update", {
                    "stage": executor_stage, "status": "running", "title": "Execution in progress",
                    "completed": index, "total": total, "passage": passage,
                })
                _campaign_event(campaign_id, "execution_completed", {
                    "stage": executor_stage, "status": "completed", "passage": passage,
                    "index": index, "total": total, "scenario_id": scenario.test_id,
                    "title": scenario.title, "question": scenario.input, "category": scenario.category.value,
                    "channels": [channel.value for channel in scenario.channels], "execution": execution,
                })

            return callback

        def record_scenario(passage: str):
            """Persist one visible result without mixing the two executor passes."""

            evaluator_stage = "evaluator" if passage == "initial" else "evaluator_confirmation"
            passage_counts = primary_counts if passage == "initial" else confirmation_counts

            def callback(
                index: int, total: int, scenario: models.TestCase, evaluation: models.EvaluationResult, execution: dict
            ) -> None:
                counts[evaluation.verdict.value] += 1
                passage_counts[evaluation.verdict.value] += 1
                _campaign_event(campaign_id, "stage_update", {
                    "stage": evaluator_stage, "status": "running", "title": "Deterministic evaluation in progress",
                    "completed": index, "total": total, "passage": passage,
                })
                critic = execution.get("critic") or {}
                evaluator_provider = (execution.get("evaluator") or {}).get("provider") or {}
                critic_provider = critic.get("provider") or {}
                if evaluator_provider.get("status") == "failed":
                    quality_fallbacks[passage]["evaluator"] += 1
                if critic_provider.get("status") == "failed":
                    quality_fallbacks[passage]["critic"] += 1
                follow_up = critic.get("follow_up_question")
                if passage == "initial" and critic.get("next_action_required") and isinstance(follow_up, str):
                    confirmation_requests.append((scenario, follow_up))
                _campaign_event(campaign_id, "scenario_completed", {
                    "stage": evaluator_stage, "status": evaluation.verdict.value,
                    "passage": passage, "index": index, "total": total, "scenario_id": scenario.test_id,
                    "title": scenario.title, "question": scenario.input, "category": scenario.category.value,
                    "channels": [channel.value for channel in scenario.channels],
                    "verdict": evaluation.verdict.value,
                    "failure_category": evaluation.failure_category.value if evaluation.failure_category else None,
                    "scores": {
                        "relevance": evaluation.relevance, "factuality": evaluation.factuality,
                        "source_fidelity": evaluation.source_fidelity, "coherence": evaluation.conversation_coherence,
                    },
                    "execution": execution,
                    "evaluator": execution.get("evaluator"),
                    "critic": critic or None,
                    "regression": execution.get("regression"),
                })

            return callback

        active_stage = "executor"
        _campaign_event(campaign_id, "stage_update", {
            "stage": "executor", "status": "running", "title": "Initial pass: API and Web execution",
            "completed": 0, "total": len(primary_selected), "passage": "initial",
        })
        api_executor = ApiExecutor(CHAT_API_URL)
        try:
            primary_report = run_scenario_batch(
                library.model_copy(update={"scenarios": primary_selected}),
                api_executor=api_executor,
                web_executor=WebExecutor(CHAT_WEB_URL) if configuration["include_web"] else None,
                include_cross_channel=configuration["include_web"],
                max_scenarios=None,
                settings=settings if groq_enabled else None,
                groq_client=groq_client,
                regression_root=PROJECT_ROOT / "data" / "autotest" / "regressions",
                planned_actions=planned_actions,
                on_execution_complete=record_execution("initial"),
                on_scenario_complete=record_scenario("initial"),
            )
        finally:
            api_executor.close()
        reports = [primary_report]
        evaluator_fallbacks = quality_fallbacks["initial"]["evaluator"]
        critic_fallbacks = quality_fallbacks["initial"]["critic"]
        _campaign_event(campaign_id, "stage_update", {
            "stage": "executor", "status": "completed", "title": "Initial pass completed",
            "completed": len(primary_report.tests), "total": len(primary_selected), "counts": primary_counts,
        })
        _campaign_event(campaign_id, "stage_update", {
            "stage": "evaluator", "status": "completed_with_fallback" if evaluator_fallbacks else "completed",
            "title": "Evaluation completed with deterministic fallback" if evaluator_fallbacks else "Initial-pass evaluation completed",
            "completed": len(primary_report.tests), "total": len(primary_selected), "counts": primary_counts,
            "quality_fallbacks": evaluator_fallbacks,
            "rule": "An optional SLM score can never change the deterministic verdict.",
        })

        if configuration["scenario_profile"] == "exploration" and groq_enabled:
            _campaign_event(campaign_id, "stage_update", {
                "stage": "critic", "status": "completed_with_fallback" if critic_fallbacks else "completed",
                "title": "Critic review completed with deterministic fallback" if critic_fallbacks else "Initial-pass Critic review completed",
                "reviewed_scenarios": len(primary_report.tests), "confirmation_requested": len(confirmation_requests),
                "quality_fallbacks": critic_fallbacks,
                "policy": "Every confirmation starts a second Planner → Executor → Evaluator pass.",
            })
            if confirmation_requests:
                _campaign_event(campaign_id, "stage_update", {
                    "stage": "planner_confirmation", "status": "running",
                    "title": "Second pass: confirmation planning",
                    "candidate_scenarios": len(confirmation_requests),
                })
                active_stage = "planner_confirmation"
                confirmation_actions: dict[str, models.PlannedAction] = {}
                confirmation_scenarios: list[models.TestCase] = []
                for parent, question in confirmation_requests:
                    scenario = parent.model_copy(update={
                        "test_id": f"{parent.test_id}-CONFIRM",
                        "title": f"Confirmation · {parent.title}",
                        "input": question,
                        "origin": "groq_critic_confirmation",
                    })
                    state = CampaignState.initialise(scenario, settings.limits)
                    action, metadata = plan_api_action(scenario, client=groq_client, campaign=state)
                    generation_groq_call_count += metadata.attempts
                    _campaign_event(campaign_id, "agent_output", {
                        "stage": "planner_confirmation", "status": "fallback_local" if metadata.status == "fallback_local" else "completed" if action else "rejected",
                        "scenario_id": scenario.test_id, "question": scenario.input,
                        "provider": metadata.trace_data(),
                    })
                    if action is not None:
                        confirmation_actions[scenario.test_id] = action
                        confirmation_scenarios.append(scenario)
                if confirmation_scenarios:
                    _campaign_event(campaign_id, "stage_update", {
                        "stage": "planner_confirmation", "status": "completed",
                        "title": "Confirmations planned",
                        "selected_scenarios": len(confirmation_scenarios),
                        "rejected_scenarios": len(confirmation_requests) - len(confirmation_scenarios),
                    })
                    _campaign_event(campaign_id, "stage_update", {
                        "stage": "executor_confirmation", "status": "running",
                        "title": "Second pass: confirmation execution",
                        "completed": 0, "total": len(confirmation_scenarios), "passage": "confirmation",
                    })
                    active_stage = "executor_confirmation"
                    api_executor = ApiExecutor(CHAT_API_URL)
                    try:
                        confirmation_report = run_scenario_batch(
                            library.model_copy(update={"scenarios": confirmation_scenarios}),
                            api_executor=api_executor,
                            include_cross_channel=False,
                            settings=settings,
                            groq_client=groq_client,
                            regression_root=PROJECT_ROOT / "data" / "autotest" / "regressions",
                            planned_actions=confirmation_actions,
                            on_execution_complete=record_execution("confirmation"),
                            on_scenario_complete=record_scenario("confirmation"),
                        )
                    finally:
                        api_executor.close()
                    reports.append(confirmation_report)
                    _campaign_event(campaign_id, "stage_update", {
                        "stage": "executor_confirmation", "status": "completed",
                        "title": "Second pass completed",
                        "completed": len(confirmation_report.tests), "total": len(confirmation_scenarios),
                        "counts": confirmation_counts,
                    })
                    _campaign_event(campaign_id, "stage_update", {
                        "stage": "evaluator_confirmation", "status": "completed",
                        "title": "Confirmation evaluation completed",
                        "completed": len(confirmation_report.tests), "total": len(confirmation_scenarios),
                        "counts": confirmation_counts,
                    })
                else:
                    for stage in ("executor_confirmation", "evaluator_confirmation"):
                        _campaign_event(campaign_id, "stage_update", {
                            "stage": stage, "status": "skipped", "title": "No confirmation authorised",
                            "reason": "The Planner rejected every Critic request.",
                        })
            else:
                for stage in ("planner_confirmation", "executor_confirmation", "evaluator_confirmation"):
                    _campaign_event(campaign_id, "stage_update", {
                        "stage": stage, "status": "skipped", "title": "Second pass not needed",
                        "reason": "The Critic requested no confirmation.",
                    })

        report = primary_report.model_copy(update={
            "tests": [test for item in reports for test in item.tests],
            "regressions": [regression for item in reports for regression in item.regressions],
            "finished_at": datetime.now(UTC),
            "groq_call_count": sum(item.groq_call_count for item in reports),
        })
        (
            json_path,
            summary_markdown_path,
            summary_html_path,
            audit_markdown_path,
            audit_html_path,
        ) = write_campaign_report(report, PROJECT_ROOT / "data" / "autotest" / "campaigns")
        result = {
            "summary": {"total": len(report.tests), **counts},
            "report_paths": {
                "json": str(json_path),
                "summary_markdown": str(summary_markdown_path),
                "summary_html": str(summary_html_path),
                "audit_markdown": str(audit_markdown_path),
                "audit_html": str(audit_html_path),
            },
            "groq_call_count": report.groq_call_count + generation_groq_call_count,
        }
        with _connection() as connection:
            connection.execute(
                "UPDATE campaigns SET status=?, updated_at=?, result=?, error=NULL WHERE id=?",
                ("completed", datetime.now(UTC).isoformat(), json.dumps(result, ensure_ascii=False), campaign_id),
            )
        _campaign_event(campaign_id, "stage_update", {
            "stage": "reporter", "status": "completed", "title": "JSON, Markdown and HTML reports generated",
            **result,
        })
        _campaign_event(campaign_id, "campaign_completed", {"status": "completed", **result})
    # The campaign boundary records unexpected provider or storage failures
    # as a terminal event for the user interface.
    except Exception as error:  # noqa: BLE001
        message = f"{type(error).__name__}: {error}"
        with _connection() as connection:
            connection.execute(
                "UPDATE campaigns SET status=?, updated_at=?, error=? WHERE id=?",
                ("technical_error", datetime.now(UTC).isoformat(), message, campaign_id),
            )
        _campaign_event(campaign_id, "stage_update", {
            "stage": active_stage, "status": "technical_error", "title": "Stage interrupted",
            "reason": str(error),
        })
        _campaign_event(campaign_id, "technical_error", {"stage": active_stage, "error": message})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "agentic-testing"}


@app.get("/api/coverage/web")
def web_coverage() -> dict:
    """Expose the last real Web campaign to the Testing application only."""
    return _web_coverage()


@app.get("/api/visual-checks/latest")
def latest_visual_check() -> dict:
    """Return the latest user-triggered Playwright run and its live log."""
    return {"visual_check": _latest_visual_check()}


@app.post("/api/visual-checks", status_code=201)
def start_visual_check(background_tasks: BackgroundTasks) -> dict:
    """Start one isolated, fixed browser test suite; concurrent runs are refused."""
    with _connection() as connection:
        active = connection.execute(
            "SELECT id FROM visual_checks WHERE status IN ('pending', 'running') ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if active:
            raise HTTPException(status_code=409, detail="A visual check is already running.")
        visual_check_id = f"VISUAL-{uuid4().hex[:12]}"
        timestamp = datetime.now(UTC).isoformat()
        connection.execute(
            "INSERT INTO visual_checks VALUES (?, ?, ?, ?, NULL, NULL)",
            (visual_check_id, "pending", timestamp, timestamp),
        )
    _visual_check_event(visual_check_id, "visual_created", {"status": "pending"})
    background_tasks.add_task(_run_visual_check, visual_check_id)
    return {"id": visual_check_id, "status": "starting"}


@app.get("/api/visual-checks/{visual_check_id}/events")
def visual_check_events(visual_check_id: str):
    _read_visual_check(visual_check_id)

    def stream():
        last_id = 0
        while True:
            with _connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM visual_check_events WHERE visual_check_id=? AND id>? ORDER BY id",
                    (visual_check_id, last_id),
                ).fetchall()
            for row in rows:
                last_id = row["id"]
                data = {"id": row["id"], "created_at": row["created_at"], **json.loads(row["data"])}
                yield f"event: {row['type']}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            if _read_visual_check(visual_check_id)["status"] in {"completed", "failed", "technical_error"}:
                break
            time.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/catalog/summary")
def catalog_summary() -> dict:
    """Expose the reproducible scenario catalogue before any campaign is started."""
    library = build_scenario_library()
    return {
        "report_count": library.report_count,
        "scenario_count": len(library.scenarios),
        "auto_validated_fact_scenarios": library.auto_validated_fact_scenario_count,
        "missing_fact_scenarios": library.missing_fact_scenario_count,
        "behavior_scenarios": library.behavior_scenario_count,
        "cross_channel_scenarios": library.cross_channel_scenario_count,
    }


@app.get("/api/catalog/scenarios")
def catalog_scenarios() -> dict:
    """List the exact planned scenarios before a campaign starts."""
    library = build_scenario_library()
    report_paths = {(item.bank_id, item.reporting_year): item.source_path for item in library.coverage}
    return {
        "generated_at": library.generated_at,
        "scenarios": [
            {
                "id": scenario.test_id,
                "title": scenario.title,
                "question": scenario.input,
                "category": scenario.category.value,
                "channels": [channel.value for channel in scenario.channels],
                "bank_id": scenario.bank_id,
                "reporting_year": scenario.reporting_year,
                "metric_id": scenario.metric_id,
                "expected_properties": scenario.expected_properties,
                "expected_description": _expected_description(scenario),
                "source_path": report_paths.get((scenario.bank_id, scenario.reporting_year)),
                "origin": scenario.origin,
            }
            for scenario in library.scenarios
        ],
    }


@app.post("/api/campaigns/catalog", status_code=201)
def start_catalog_campaign(body: StartCatalogCampaignRequest, background_tasks: BackgroundTasks) -> dict:
    """Start either the archived catalogue or an AI-generated exploration campaign."""
    if body.scenario_profile == "exploration" and not load_settings().groq_api_key:
        raise HTTPException(
            status_code=412,
            detail="The exploratory campaign requires GROQ_API_KEY in the Testing service environment.",
        )
    with _connection() as connection:
        active = connection.execute("SELECT id FROM campaigns WHERE status IN ('pending', 'running') LIMIT 1").fetchone()
        if active is not None:
            raise HTTPException(status_code=409, detail=f"Campaign {active['id']} is already running.")
        campaign_id = f"CAMPAIGN-{uuid4().hex[:12]}"
        timestamp = datetime.now(UTC).isoformat()
        configuration = {
            "include_web": body.include_web,
            "with_groq": body.with_groq,
            "max_scenarios": body.max_scenarios,
            "scenario_profile": body.scenario_profile,
            "trigger": "diagnostic" if body.max_scenarios is not None else "dashboard",
        }
        connection.execute(
            "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, NULL, NULL)",
            (campaign_id, "pending", timestamp, timestamp, json.dumps(configuration, ensure_ascii=False)),
        )
    _campaign_event(campaign_id, "campaign_created", {"stage": "generator", "status": "pending", "configuration": configuration})
    background_tasks.add_task(_run_catalog_campaign, campaign_id)
    return {"id": campaign_id, "status": "starting"}


@app.get("/api/campaigns")
def list_campaigns() -> dict:
    with _connection() as connection:
        rows = connection.execute("SELECT id FROM campaigns ORDER BY created_at DESC LIMIT 30").fetchall()
    return {"campaigns": [_read_campaign(row["id"]) for row in rows]}


@app.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: str) -> dict:
    return _read_campaign(campaign_id)


@app.get("/api/campaigns/{campaign_id}/reports/{report_format}")
def get_campaign_report(campaign_id: str, report_format: str):
    """Serve only a report artifact recorded for this campaign."""
    media_types = {
        "json": "application/json",
        "markdown": "text/markdown; charset=utf-8",
        "html": "text/html; charset=utf-8",
        "summary_markdown": "text/markdown; charset=utf-8",
        "summary_html": "text/html; charset=utf-8",
        "audit_markdown": "text/markdown; charset=utf-8",
        "audit_html": "text/html; charset=utf-8",
    }
    if report_format not in media_types:
        raise HTTPException(status_code=404, detail="Unknown report format.")
    campaign = _read_campaign(campaign_id)
    report_paths = (campaign.get("result") or {}).get("report_paths", {})
    raw_path = report_paths.get(report_format)
    if not isinstance(raw_path, str) and report_format in {
        "summary_markdown",
        "summary_html",
        "audit_markdown",
        "audit_html",
    }:
        legacy_json_path = report_paths.get("json")
        if isinstance(legacy_json_path, str) and Path(legacy_json_path).is_file():
            legacy_report = models.FinalReport.model_validate_json(Path(legacy_json_path).read_text(encoding="utf-8"))
            generated_paths = write_campaign_report(legacy_report, CAMPAIGN_REPORT_ROOT)
            generated_by_format = dict(
                zip(
                    ("json", "summary_markdown", "summary_html", "audit_markdown", "audit_html"),
                    generated_paths,
                    strict=True,
                )
            )
            raw_path = str(generated_by_format[report_format])
    if not isinstance(raw_path, str):
        raise HTTPException(status_code=404, detail="This report is not available yet.")
    report_path = Path(raw_path).resolve()
    report_root = CAMPAIGN_REPORT_ROOT.resolve()
    if report_root not in report_path.parents or not report_path.is_file():
        raise HTTPException(status_code=404, detail="The report file was not found.")
    extension = {
        "json": "json",
        "markdown": "md",
        "html": "html",
        "summary_markdown": "md",
        "summary_html": "html",
        "audit_markdown": "md",
        "audit_html": "html",
    }[report_format]
    return FileResponse(
        report_path,
        media_type=media_types[report_format],
        filename=f"{campaign_id}-report.{extension}" if not report_format.endswith("_html") and report_format != "html" else None,
    )


@app.get("/api/campaigns/{campaign_id}/events")
def campaign_events(campaign_id: str):
    _read_campaign(campaign_id)

    def stream():
        last_id = 0
        while True:
            with _connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM campaign_events WHERE campaign_id=? AND id>? ORDER BY id",
                    (campaign_id, last_id),
                ).fetchall()
            for row in rows:
                last_id = row["id"]
                data = {"id": row["id"], "created_at": row["created_at"], **json.loads(row["data"])}
                yield f"event: {row['type']}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            status = _read_campaign(campaign_id)["status"]
            if status in {"completed", "technical_error"}:
                break
            time.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/tests", status_code=201)
def create_test(body: CreateTestRequest) -> dict:
    test_id = f"TEST-{uuid4().hex[:12]}"
    timestamp = datetime.now(UTC).isoformat()
    with _connection() as connection:
        connection.execute("INSERT INTO tests VALUES (?, ?, ?, ?, ?, NULL, NULL)", (test_id, "pending", timestamp, timestamp, body.model_dump_json()))
    _event(test_id, "test_created", {"step": "observation", "origin": body.origin})
    return {"id": test_id, "status": "pending"}


@app.get("/api/tests")
def list_tests() -> dict:
    with _connection() as connection:
        rows = connection.execute("SELECT id FROM tests ORDER BY created_at DESC LIMIT 100").fetchall()
    return {"tests": [_read_test(row["id"]) for row in rows]}


@app.get("/api/tests/{test_id}")
def get_test(test_id: str) -> dict:
    return _read_test(test_id)


@app.post("/api/tests/{test_id}/start")
def start_test(test_id: str, background_tasks: BackgroundTasks) -> dict:
    test = _read_test(test_id)
    if test["status"] not in {"pending", "failed", "inconclusive", "technical_error", "cancelled"}:
        raise HTTPException(status_code=409, detail="This test is already running or completed successfully.")
    background_tasks.add_task(_run, test_id)
    return {"id": test_id, "status": "starting"}


@app.post("/api/tests/{test_id}/stop")
def stop_test(test_id: str) -> dict:
    test = _read_test(test_id)
    if test["status"] == "running":
        raise HTTPException(status_code=409, detail="A running API execution cannot yet be stopped safely.")
    with _connection() as connection:
        connection.execute("UPDATE tests SET status=?, updated_at=? WHERE id=?", ("cancelled", datetime.now(UTC).isoformat(), test_id))
    _event(test_id, "test_cancelled", {"step": "decision"})
    return {"id": test_id, "status": "cancelled"}


@app.get("/api/tests/{test_id}/events")
def events(test_id: str):
    _read_test(test_id)
    def stream():
        last_id = 0
        while True:
            with _connection() as connection:
                rows = connection.execute("SELECT * FROM events WHERE test_id=? AND id>? ORDER BY id", (test_id, last_id)).fetchall()
            for row in rows:
                last_id = row["id"]
                yield f"event: {row['type']}\ndata: {json.dumps({'id': row['id'], 'created_at': row['created_at'], **json.loads(row['data'])}, ensure_ascii=False)}\n\n"
            status = _read_test(test_id)["status"]
            if status in {"passed", "failed", "technical_error", "cancelled"}:
                break
            time.sleep(0.5)
    return StreamingResponse(stream(), media_type="text/event-stream")
