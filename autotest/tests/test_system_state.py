"""Read-only stack diagnostics used by the Agentic Testing dashboard."""

from myfinance_testing_api import main


def test_system_state_marks_enriched_stack_ready(monkeypatch) -> None:
    responses = {
        f"{main.CHAT_API_URL}/health": {"status": "ok"},
        f"{main.CHAT_API_URL}/api/status": {"router_revision": "routing-v1", "llm_provider": "groq"},
        f"{main.QDRANT_URL}/collections/{main.QDRANT_COLLECTION}": {"result": {"points_count": 3440}},
        f"{main.OLLAMA_URL}/api/tags": {"models": [{"name": "nomic-embed-text:latest"}]},
        f"{main.CHAT_API_URL}/api/market/collection-health": {
            "fresh": True, "retrieved_at": "2026-08-22T20:54:40+00:00", "observation_count": 8,
        },
    }

    monkeypatch.setattr(main, "_fetch_json", lambda url, **_: (responses.get(url), None))

    state = main.system_state()

    assert state["overall"] == "ready"
    assert state["catalog"]["behavior_scenario_count"] == 11
    assert {item["status"] for item in state["components"]} == {"ready"}


def test_system_state_keeps_safe_fallbacks_visible(monkeypatch) -> None:
    def fetch(url: str, **_) -> tuple[dict | None, str | None]:
        if url.endswith("/health"):
            return {"status": "ok"}, None
        if url.endswith("/api/status"):
            return {"router_revision": "routing-v1"}, None
        if url.endswith("collection-health"):
            return {"fresh": False, "status": "no_snapshots", "alerts": []}, None
        return None, "URLError"

    monkeypatch.setattr(main, "_fetch_json", fetch)

    state = main.system_state()

    assert state["overall"] == "attention"
    components = {item["name"]: item for item in state["components"]}
    assert components["chat_api"]["status"] == "ready"
    assert components["qdrant"]["status"] == "degraded"
    assert components["market_collector"]["status"] == "degraded"
