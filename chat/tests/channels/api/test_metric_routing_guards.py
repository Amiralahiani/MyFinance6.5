from fastapi.testclient import TestClient
from myfinance_contracts import ConversationContext
from myfinance_orchestrator import dialogue
from myfinance_orchestrator.main import app

client = TestClient(app)


def test_explicit_metric_escapes_a_failed_documentary_context() -> None:
    context = ConversationContext(
        mode="document",
        bank_id="biat",
        bank_name="BIAT",
        reporting_year=2023,
        document_query="a documentary request with no matching passage",
        document_search_status="no_evidence",
    )

    response = client.post(
        "/api/conversation/answer",
        json={"message": "What is the PNB of BIAT in 2023?", "context": context.model_dump()},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "numeric"
    assert response.json()["metric_id"] == "net_banking_income"
    assert response.json()["value"] == "1396872"


def test_validated_metric_precedes_a_reporting_agent_route(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "_classify_agent_route",
        lambda *args, **kwargs: "reporting",
    )

    response = client.post(
        "/api/conversation/answer",
        json={"message": "What is the PNB of BIAT in 2023?", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "numeric"
    assert response.json()["metric_id"] == "net_banking_income"


def test_current_quote_does_not_inherit_a_report_year(monkeypatch) -> None:
    received: dict[str, object] = {}

    monkeypatch.setattr(dialogue, "_classify_agent_route", lambda *args, **kwargs: "market")
    monkeypatch.setattr(dialogue, "_classify_market_request", lambda *args, **kwargs: "current_quote")

    def fake_market_turn(context, bank_ids, year, request_kind, **kwargs):
        received.update(bank_ids=bank_ids, year=year, request_kind=request_kind)
        return {"type": "market_quote", "mode": "market", "context": context.model_dump()}

    monkeypatch.setattr(dialogue, "_market_turn", fake_market_turn)
    context = ConversationContext(
        mode="document",
        bank_id="biat",
        bank_name="BIAT",
        reporting_year=2021,
    )

    result = dialogue.answer_conversation_turn("Quel est le cours actuel de l'action BIAT ?", context)

    assert result["type"] == "market_quote"
    assert received == {"bank_ids": ["biat"], "year": None, "request_kind": "current_quote"}


def test_short_country_followup_stays_in_a_general_conversation(monkeypatch) -> None:
    monkeypatch.setattr(dialogue, "_classify_agent_route", lambda *args, **kwargs: "market")
    monkeypatch.setattr(dialogue, "complete", lambda *args, **kwargs: "France's main stock-market index is the CAC 40.")
    context = ConversationContext(
        mode="general",
        topic="the main stock-market index in Tunisia",
        general_last_answer="Tunisia's main stock-market index is TUNINDEX.",
    )

    result = dialogue.answer_conversation_turn("and in France", context)

    assert result["type"] == "general"
    assert result["context"]["mode"] == "general"
    assert result["answer"] == "France's main stock-market index is the CAC 40."
