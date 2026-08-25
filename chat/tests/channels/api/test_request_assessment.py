import pytest
from fastapi.testclient import TestClient
from myfinance_contracts import ConversationContext
from myfinance_orchestrator import dialogue, language
from myfinance_orchestrator.language import correct_financial_spelling, normalise_financial_request
from myfinance_orchestrator.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def disable_external_conversation_router(monkeypatch):
    """Tests mock model decisions explicitly; they never call a live provider."""
    monkeypatch.setenv("MYFINANCE_CONVERSATION_ROUTER", "false")


def test_financial_spelling_repair_corrects_a_known_financial_term() -> None:
    message, corrections = correct_financial_spelling("Explique le potfeuille d'encaissement de BIAT")

    assert message == "Explique le portefeuille d'encaissement de BIAT"
    assert corrections == [{"from": "potfeuille", "to": "portefeuille"}]


def test_financial_spelling_repair_does_not_replace_valid_document_terms() -> None:
    message, corrections = correct_financial_spelling("Transactions avec les parties liées")

    assert message == "Transactions avec les parties liées"
    assert corrections == []


def test_financial_spelling_repair_never_rewrites_ordinary_french_prose() -> None:
    message, corrections = correct_financial_spelling("Quelles sont les autres conventions après GSM ?")

    assert message == "Quelles sont les autres conventions après GSM ?"
    assert corrections == []


@pytest.mark.parametrize(
    ("question", "expected_fragment"),
    [
        ("Give me BIAT's 2025 net banking income without citing the report.", "official report"),
        ("Give BIAT's 2025 net income in US dollars, without approximation.", "exchange-rate source"),
        ("What was the balance of my bank account at the end of 2019?", "personal bank-account"),
        ("Which bank is the safest according to your reports?", "cannot rank banks"),
    ],
)
def test_safety_guards_refuse_unsafe_requests_before_metric_lookup(question: str, expected_fragment: str) -> None:
    response = dialogue.answer_conversation_turn(question, ConversationContext())

    assert response["type"] == "clarification"
    assert "value" not in response
    assert expected_fragment in response["message"]


def test_unavailable_year_is_explained_without_calling_the_conversation_router() -> None:
    response = dialogue.answer_conversation_turn("What was BIAT's net banking income in 2035?", ConversationContext())

    assert response["type"] == "clarification"
    assert "value" not in response
    assert "requested year" in response["message"]


def test_explicit_two_bank_metric_request_uses_the_comparison_route() -> None:
    response = dialogue.answer_conversation_turn(
        "What was the net banking income of BIAT and Amen Bank in 2025?", ConversationContext()
    )

    assert response["type"] == "comparison"
    assert {item["bank_id"] for item in response["values"]} == {"biat", "amen_bank"}


def test_document_reformulation_replaces_a_topic_after_a_failed_search(monkeypatch) -> None:
    searched: list[str] = []
    monkeypatch.setattr(
        dialogue,
        "retrieve_evidence",
        lambda _bank, _year, query, **_kwargs: searched.append(query) or [],
    )
    context = ConversationContext(
        mode="document",
        bank_id="biat",
        bank_name="BIAT",
        reporting_year=2023,
        topic="what is the portfolio of BIAT in 2023",
        document_query="what is the portfolio of BIAT in 2023",
        document_search_status="no_evidence",
    )

    response = dialogue._document_turn(
        "le portefeuille", context, "biat", 2023,
        continuation=True, expand_scope=False, document_scope=None,
    )

    assert response["context"]["topic"] == "le portefeuille"
    assert response["context"]["document_search_status"] == "no_evidence"
    assert searched and "le portefeuille" in searched[0]


def test_documentary_glossary_resolves_portfolio_to_official_report_terms(monkeypatch) -> None:
    monkeypatch.setattr(dialogue, "answer_from_evidence", lambda *_args, **_kwargs: "Source-grounded portfolio explanation.")

    response = dialogue._document_turn(
        "portfolio BIAT 2025", ConversationContext(), "biat", 2025,
        continuation=False, expand_scope=False, document_scope=None,
    )

    assert response["type"] == "document"
    assert response["context"]["document_search_status"] == "found"
    assert any(item["page_number"] == 15 for item in response["evidence"])


def test_portfolio_typo_and_later_year_keep_the_bilingual_concept(monkeypatch) -> None:
    corrected, corrections = correct_financial_spelling("wht is the potfolio of biat")
    assert corrected == "wht is the portfolio of biat"
    assert corrections == [{"from": "potfolio", "to": "portfolio"}]
    monkeypatch.setattr(
        dialogue,
        "answer_from_evidence",
        lambda _question, _evidence: "The report distinguishes a commercial securities portfolio. [p. 15]",
    )
    context = ConversationContext(
        mode="document",
        bank_id="biat",
        bank_name="BIAT",
        topic=corrected,
        document_query=corrected,
    )

    response = dialogue._document_turn(
        "in 2025", context, "biat", 2025,
        continuation=True, expand_scope=False, document_scope=None,
    )

    assert response["type"] == "document"
    assert any(item["page_number"] == 15 for item in response["evidence"])
    assert "commercial securities portfolio" in response["answer"]
    assert "Answer based directly" not in response["answer"]


def test_investment_portfolio_refines_an_active_generic_portfolio_search(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "answer_from_evidence",
        lambda _question, _evidence: "The passage concerns BIAT’s investment securities portfolio. [p. 8]",
    )
    context = ConversationContext(
        mode="document",
        bank_id="biat",
        bank_name="BIAT",
        reporting_year=2025,
        topic="what is the portfolio of biat",
        document_query="what is the portfolio of biat",
        document_search_status="found",
    )

    response = dialogue._document_turn(
        "investment portfolio", context, "biat", 2025,
        continuation=True, expand_scope=False, document_scope=None,
    )

    assert response["type"] == "document"
    assert response["context"]["topic"] == "investment portfolio"
    assert any(item["page_number"] == 8 for item in response["evidence"])
    assert "investment securities portfolio" in response["answer"]


@pytest.mark.parametrize(
    ("question", "official_term"),
    [
        ("What are the customer deposits?", "dépôts et avoirs de la clientèle"),
        ("Explain BIAT's loan book", "créances sur la clientèle"),
        ("What does credit risk mean in this report?", "risque de crédit"),
    ],
)
def test_bilingual_documentary_bridge_maps_user_terms_to_official_french_terms(question, official_term) -> None:
    assert official_term in dialogue._document_query_expansion(question)


def test_document_confirmation_after_a_failed_search_does_not_repeat_retrieval(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "retrieve_evidence",
        lambda *_args, **_kwargs: pytest.fail("a generic confirmation must not replay a failed search"),
    )
    context = ConversationContext(
        mode="document",
        bank_id="biat",
        bank_name="BIAT",
        reporting_year=2023,
        topic="le portefeuille",
        document_query="le portefeuille",
        document_search_status="no_evidence",
    )

    response = dialogue._document_turn(
        "are you sure", context, "biat", 2023,
        continuation=True, expand_scope=False, document_scope=None,
    )

    assert "do not want to guess" in response["message"]
    assert "portfolio category" in response["message"]


def test_market_turn_routes_to_the_market_agent_without_reading_a_report(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "_turn_plan",
        lambda *_args: {
            "operation": "market",
            "bank_scope": "explicit",
            "period_scope": "none",
            "metric_scope": "none",
            "document_action": "new",
            "document_scope": "none",
            "clarification": "",
        },
    )
    monkeypatch.setattr(
        dialogue,
        "retrieve_evidence",
        lambda *_args, **_kwargs: pytest.fail("a market request must not query report evidence"),
    )
    monkeypatch.setattr(
        dialogue,
        "current_market_quote",
        lambda _bank_id: {
            "bank_id": "biat", "bank_name": "BIAT", "mnemonic": "BIAT", "isin": "TN0001800457",
            "price": 164.0, "change_percent": 0.0, "currency": "Dinar Tunisien",
            "source_url": "https://tunis-stockexchange.com/market-watch",
            "retrieved_at": "2026-08-12T11:00:00Z", "delay_notice": "15 minutes",
        },
    )

    response = dialogue.answer_conversation_turn("What is BIAT's share price?", ConversationContext())

    assert response["type"] == "market_quote"
    assert response["mode"] == "market"
    assert response["context"]["market_bank_ids"] == ["biat"]
    assert response["quote"]["mnemonic"] == "BIAT"


def test_market_turn_retains_its_bank_context_for_a_follow_up(monkeypatch) -> None:
    context = ConversationContext(mode="market", market_bank_ids=["biat"])
    assessment = dialogue.assess_request("and the share price?")
    plan = {
        "operation": "market",
        "bank_scope": "active_market",
        "period_scope": "none",
        "metric_scope": "none",
        "document_action": "new",
        "document_scope": "none",
        "clarification": "",
    }

    assert dialogue._plan_banks(plan, context, assessment) == ["biat"]


def test_router_decides_that_a_market_question_goes_to_market_agent(monkeypatch) -> None:
    monkeypatch.setattr(dialogue, "_classify_agent_route", lambda *_args: "market")
    monkeypatch.setattr(
        dialogue,
        "_classify_conversation_intent",
        lambda *_args, **_kwargs: {
            "operation": "clarify",
            "bank_scope": "none",
            "period_scope": "none",
            "metric_scope": "none",
            "document_action": "new",
            "document_scope": "none",
            "clarification": "",
        },
    )
    monkeypatch.setattr(
        dialogue,
        "retrieve_evidence",
        lambda *_args, **_kwargs: pytest.fail("a market question must never query report evidence"),
    )
    monkeypatch.setattr(
        dialogue,
        "current_market_quote",
        lambda _bank_id: {
            "bank_id": "attijari_bank", "bank_name": "Attijari Bank", "mnemonic": "TJARI", "isin": "TN0001600154",
            "price": 90.0, "change_percent": 0.02, "currency": "Dinar Tunisien",
            "source_url": "https://tunis-stockexchange.com/market-watch",
            "retrieved_at": "2026-08-12T11:00:00Z", "delay_notice": "15 minutes",
        },
    )

    response = dialogue.answer_conversation_turn("How did Attijari Bank stock perform?", ConversationContext())

    assert response["type"] == "market_quote"
    assert response["mode"] == "market"


def test_market_agent_returns_a_structured_notice_when_a_current_quote_cannot_be_requested() -> None:
    missing_bank = dialogue._market_turn(ConversationContext(), [], None)
    historical = dialogue._market_turn(ConversationContext(), ["biat"], 2021)

    assert missing_bank["type"] == "market_notice"
    assert missing_bank["title"] == "Choose a listed bank"
    assert historical["type"] == "market_notice"
    assert historical["title"] == "Historical quote not available"


def test_market_agent_compares_current_quotes_instead_of_requesting_one_bank(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "current_market_quotes",
        lambda _bank_ids: [
            {"bank_id": "biat", "bank_name": "BIAT", "mnemonic": "BIAT", "isin": "TN0001800457", "price": 163.3, "change_percent": -0.43, "currency": "Dinar Tunisien", "source_url": "https://tunis-stockexchange.com/market-watch", "retrieved_at": "2026-08-12T11:00:00Z", "delay_notice": "15 minutes"},
            {"bank_id": "amen_bank", "bank_name": "Amen Bank", "mnemonic": "AB", "isin": "TN0003400408", "price": 92.3, "change_percent": -0.43, "currency": "Dinar Tunisien", "source_url": "https://tunis-stockexchange.com/market-watch", "retrieved_at": "2026-08-12T11:00:00Z", "delay_notice": "15 minutes"},
        ],
    )

    response = dialogue._market_turn(ConversationContext(), ["biat", "amen_bank"], None)

    assert response["type"] == "market_comparison"
    assert [quote["bank_id"] for quote in response["quotes"]] == ["biat", "amen_bank"]


def test_market_agent_returns_the_official_whole_market_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "current_market_summary",
        lambda: {
            "market_capitalization_tnd": 48_751_683_599.0,
            "traded_value_tnd": 6_008_398.0,
            "traded_quantity": 613_115.0,
            "transactions": 1_615.0,
            "advances": 19.0,
            "declines": 26.0,
            "active_values": 64,
            "listed_values": 75,
            "source_url": "https://tunis-stockexchange.com/market-watch",
            "retrieved_at": "2026-08-12T12:00:00Z",
            "delay_notice": "15 minutes",
        },
    )

    response = dialogue._market_turn(ConversationContext(), [], None, "market_overview")

    assert response["type"] == "market_overview"
    assert response["summary"]["transactions"] == 1_615.0


def test_market_overview_route_never_queries_report_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "_turn_plan",
        lambda *_args: {
            "operation": "market", "bank_scope": "none", "period_scope": "none",
            "metric_scope": "none", "document_action": "new", "document_scope": "none", "clarification": "",
        },
    )
    monkeypatch.setattr(dialogue, "_classify_market_request", lambda *_args: "market_overview")
    monkeypatch.setattr(
        dialogue,
        "retrieve_evidence",
        lambda *_args, **_kwargs: pytest.fail("a market overview must not query report evidence"),
    )
    monkeypatch.setattr(
        dialogue,
        "current_market_summary",
        lambda: {
            "market_capitalization_tnd": 1.0, "traded_value_tnd": 2.0, "traded_quantity": 3.0,
            "transactions": 4.0, "advances": 5.0, "declines": 6.0, "active_values": 7,
            "listed_values": 8, "source_url": "https://tunis-stockexchange.com/market-watch",
            "retrieved_at": "2026-08-12T12:00:00Z", "delay_notice": "15 minutes",
        },
    )

    response = dialogue.answer_conversation_turn("How is the Tunis stock market doing today?", ConversationContext())

    assert response["type"] == "market_overview"
    assert response["mode"] == "market"


def test_market_agent_returns_a_traceable_historical_performance(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "historical_market_performance",
        lambda bank_id, year: {
            "bank_id": bank_id, "bank_name": "BIAT", "mnemonic": "BIAT", "isin": "TN0001800457",
            "currency": "Dinar Tunisien", "year": year, "first_close": 100.0, "first_date": "2026-01-02",
            "last_close": 120.0, "last_date": "2026-06-30", "performance_percent": 20.0,
            "points": [{"date": "2026-01-02", "close": 100.0}, {"date": "2026-06-30", "close": 120.0}],
            "source_url": "https://tunis-stockexchange.com/sites/default/files/historique/data_json/market_resume.ndjson",
            "retrieved_at": "2026-08-12T12:00:00Z", "last_observation_date": "2026-06-30",
        },
    )

    response = dialogue._market_turn(ConversationContext(), ["biat"], 2026, "historical_performance")

    assert response["type"] == "market_performance"
    assert response["performance"]["performance_percent"] == 20.0
    assert response["performance"]["last_date"] == "2026-06-30"


def test_market_agent_returns_available_instrument_activity(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "historical_market_performance",
        lambda bank_id, year: {
            "bank_id": bank_id, "bank_name": "BIAT", "mnemonic": "BIAT", "currency": "Dinar Tunisien",
            "year": year, "points": [{"date": "2026-06-30", "close": 120.0, "volume": 5000,
            "turnover_tnd": 600000.0, "transactions": 15, "market_capitalization_md": 1234.5}],
            "source_url": "https://tunis-stockexchange.com/history", "retrieved_at": "2026-08-12T12:00:00Z",
        },
    )

    response = dialogue._market_turn(ConversationContext(), ["biat"], 2026, "instrument_activity")

    assert response["type"] == "market_activity"
    assert response["activity"]["metrics"]["volume"] == 5000


def test_market_date_range_accepts_only_a_chronological_same_year_pair() -> None:
    assert dialogue._market_date_range("BIAT from 2026-01-02 to 2026-06-30") == ("2026-01-02", "2026-06-30")
    assert dialogue._market_date_range("from 2026-06-30 to 2027-01-02") == ("2026-06-30", "2027-01-02")


def test_share_structure_question_requires_a_report_year_not_a_market_quote(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "current_market_quote",
        lambda *_args: pytest.fail("share structure must not read Market Watch"),
    )

    response = dialogue.answer_conversation_turn("combien BIAT a d'actions ?", ConversationContext())

    assert response["type"] == "clarification"
    assert response["mode"] == "document"
    assert response["missing_information"] == ["reporting year or period"]


def test_share_structure_question_returns_the_sourced_number_of_shares(monkeypatch) -> None:
    source = SimpleNamespace(
        text="Nombre d'actions ordinaires en circulation fin de la période  40 800 000",
        page_number=25,
        model_dump=lambda: {"chunk_id": "test", "bank_name": "BIAT", "reporting_year": 2025,
                             "page_number": 25, "source_path": "biat.pdf", "text": "source"},
    )
    monkeypatch.setattr(dialogue, "retrieve_evidence", lambda *_args, **_kwargs: [source])

    response = dialogue.answer_conversation_turn("De combien d'actions est composé le capital social de BIAT en 2025 ?", ConversationContext())

    assert response["type"] == "document"
    assert "40,800,000" in response["answer"]
    assert response["evidence"][0]["page_number"] == 25


def test_share_count_uses_the_requested_year_column_only() -> None:
    assert dialogue._share_count(
        "Nombre d'actions ordinaires en circulation fin de la période  40 800 000  40 800 000"
    ) == 40_800_000


def test_share_structure_question_recognises_common_french_variants() -> None:
    assert dialogue._is_share_structure_question("Combien de titres BIAT a en 2025 ?")
    assert dialogue._is_share_structure_question("Quelle est la composition du capital sociale de BIAT ?")
    assert dialogue._is_share_structure_question("Quel est le nbre d'actoin de BIAT ?")


def test_explicit_current_share_price_routes_to_market_without_the_optional_router(monkeypatch) -> None:
    received: dict[str, object] = {}

    def market_turn(context, bank_ids, year, request_kind, **kwargs):
        received.update(bank_ids=bank_ids, year=year, request_kind=request_kind)
        return {"type": "market_quote", "mode": "market"}

    monkeypatch.setattr(dialogue, "_market_turn", market_turn)

    response = dialogue.answer_conversation_turn("What is BIAT's current share price?", ConversationContext())

    assert response["type"] == "market_quote"
    assert received == {"bank_ids": ["biat"], "year": None, "request_kind": "current_quote"}


def test_multiple_named_banks_without_a_criterion_receive_a_specific_clarification() -> None:
    response = dialogue.answer_conversation_turn("Compare BIAT, BT and Amen Bank.", ConversationContext())

    assert response["type"] == "clarification"
    assert "current share prices" in response["message"]
    assert "financial metric" in response["message"]


def test_market_comparison_clarification_retains_the_named_banks_for_the_follow_up(monkeypatch) -> None:
    pending = dialogue.answer_conversation_turn("Compare BIAT, BT and Amen Bank.", ConversationContext())
    received: dict[str, object] = {}

    def market_turn(context, bank_ids, year, request_kind, **kwargs):
        received.update(bank_ids=bank_ids, year=year, request_kind=request_kind)
        return {"type": "market_comparison", "mode": "market"}

    monkeypatch.setattr(dialogue, "_market_turn", market_turn)
    response = dialogue.answer_conversation_turn(
        "current share prices",
        ConversationContext.model_validate(pending["context"]),
    )

    assert response["type"] == "market_comparison"
    assert set(received["bank_ids"]) == {"amen_bank", "biat", "bt"}
    assert received["year"] is None
    assert received["request_kind"] == "current_quote"


def test_market_quote_context_makes_an_unqualified_bank_comparison_use_current_prices(monkeypatch) -> None:
    received: dict[str, object] = {}

    def market_turn(context, bank_ids, year, request_kind, **kwargs):
        received.update(bank_ids=bank_ids, year=year, request_kind=request_kind)
        return {"type": "market_comparison", "mode": "market"}

    monkeypatch.setattr(dialogue, "_market_turn", market_turn)
    response = dialogue.answer_conversation_turn(
        "Compare BIAT, BT and Amen Bank.",
        ConversationContext(mode="market", market_bank_ids=["biat"], topic="market_data"),
    )

    assert response["type"] == "market_comparison"
    assert set(received["bank_ids"]) == {"amen_bank", "biat", "bt"}
    assert received["year"] is None
    assert received["request_kind"] == "current_quote"


@pytest.mark.parametrize(
    ("question", "unknown_bank"),
    [
        ("what is the pnb of biat and bt and x in 2021", "X"),
        ("what is the pnb of vcg in 2023", "VCG"),
    ],
)
def test_explicit_unknown_bank_never_falls_back_to_a_previous_context(question: str, unknown_bank: str) -> None:
    response = dialogue.answer_conversation_turn(
        question,
        ConversationContext(
            mode="comparison",
            comparison_bank_ids=["biat", "bt"],
            metric_id="net_banking_income",
            reporting_year=2021,
        ),
    )

    assert response["type"] == "clarification"
    assert unknown_bank in response["message"]
    assert response["context"]["mode"] == "idle"


def test_plain_bank_selection_requires_an_explicit_year_for_a_metric_follow_up() -> None:
    selection = client.post(
        "/api/conversation/answer",
        json={"message": "Banque Zitouna", "context": {}},
    )
    pending = client.post(
        "/api/conversation/answer",
        json={"message": "what is its pnb", "context": selection.json()["context"]},
    )
    resolved = client.post(
        "/api/conversation/answer",
        json={"message": "in 2023", "context": pending.json()["context"]},
    )

    assert selection.status_code == 200
    assert selection.json()["context"]["bank_id"] == "zitouna"
    assert selection.json()["context"]["reporting_year"] is None
    assert "selected" in selection.json()["answer"].lower()
    assert pending.status_code == 200
    assert pending.json()["type"] == "clarification"
    assert pending.json()["missing_information"] == ["reporting year or period"]
    assert "which reporting year" in pending.json()["message"].lower()
    assert resolved.status_code == 200
    assert resolved.json()["type"] == "numeric"
    assert resolved.json()["reporting_year"] == 2023


def test_bank_and_year_without_a_metric_returns_a_fast_clarification(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "_classify_agent_route",
        lambda *_args, **_kwargs: pytest.fail("a missing metric must not call the semantic router"),
    )
    monkeypatch.setattr(
        dialogue,
        "_classify_conversation_intent",
        lambda *_args, **_kwargs: pytest.fail("a missing metric must not call the conversation classifier"),
    )

    response = dialogue.answer_conversation_turn(
        "Could you clarify whether you have access to BIAT's 2023 financial statements?",
        ConversationContext(),
    )

    assert response["type"] == "clarification"
    assert response["context"]["bank_id"] == "biat"
    assert response["context"]["reporting_year"] == 2023
    assert response["missing_information"] == ["financial metric to analyse"]
    assert "net banking income" in response["message"]


def test_english_share_count_question_never_routes_to_the_capital_amount(monkeypatch) -> None:
    source = SimpleNamespace(
        text="Nombre d'actions ordinaires en circulation fin de la période  40 800 000",
        page_number=25,
        model_dump=lambda: {"chunk_id": "test", "bank_name": "BIAT", "reporting_year": 2025,
                             "page_number": 25, "source_path": "biat.pdf", "text": "source"},
    )
    monkeypatch.setattr(dialogue, "retrieve_evidence", lambda *_args, **_kwargs: [source])

    response = dialogue.answer_conversation_turn(
        "How many shares made up BIAT's share capital in 2025?",
        ConversationContext(),
    )

    assert response["type"] == "document"
    assert "40,800,000" in response["answer"]


def test_router_unavailability_never_guesses_documentary_for_a_semantic_request(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "retrieve_evidence",
        lambda *_args, **_kwargs: pytest.fail("a market follow-up must not query report evidence"),
    )
    monkeypatch.setattr(dialogue, "_classify_conversation_intent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dialogue, "_classify_agent_route", lambda *_args, **_kwargs: None)

    response = dialogue.answer_conversation_turn("How did Attijari Bank stock perform in 2021?", ConversationContext())

    assert response["type"] == "clarification"
    assert response["mode"] == "idle"


def test_failed_document_confirmation_stays_in_its_dossier_even_if_the_router_misclassifies(monkeypatch) -> None:
    monkeypatch.setattr(
        dialogue,
        "_classify_conversation_intent",
        lambda *_args, **_kwargs: {"operation": "general_education", "bank_scope": "none", "period_scope": "none", "metric_scope": "none"},
    )
    monkeypatch.setattr(
        dialogue,
        "retrieve_evidence",
        lambda *_args, **_kwargs: pytest.fail("a generic confirmation must not replay a failed search"),
    )
    context = ConversationContext(
        mode="document",
        bank_id="biat",
        bank_name="BIAT",
        reporting_year=2023,
        topic="le portefeuille",
        document_query="le portefeuille",
        document_search_status="no_evidence",
    )

    response = dialogue.answer_conversation_turn("are you sure", context)

    assert response["type"] == "clarification"
    assert "do not want to guess" in response["message"]


def test_normalize_endpoint_returns_one_interpreted_sentence_not_word_by_word_feedback() -> None:
    response = client.post("/api/requests/normalize", json={"message": "potfeuille d'encaissement"})

    assert response.status_code == 200
    assert response.json()["message"] == "portefeuille d'encaissement"
    assert response.json()["corrections"] == [{"from": "potfeuille d'encaissement", "to": "portefeuille d'encaissement"}]


def test_request_normalisation_repairs_a_malformed_bank_question_as_one_sentence() -> None:
    message, corrections = normalise_financial_request("whatsbiat ?")

    assert message == "what is biat ?"
    assert corrections == [{"from": "whatsbiat ?", "to": "what is biat ?"}]


def test_request_normalisation_can_use_a_full_sentence_rewrite_without_answering(monkeypatch) -> None:
    monkeypatch.setenv("MYFINANCE_QUERY_REWRITE", "true")
    monkeypatch.setattr(language, "json_object", lambda *args, **kwargs: {"message": "What is BIAT?"})

    message, corrections = normalise_financial_request("whats biat")

    assert message == "What is BIAT?"
    assert corrections == [{"from": "whats biat", "to": "What is BIAT?"}]


def test_catalog_contains_the_25_expected_reports() -> None:
    response = client.get("/api/reports")

    assert response.status_code == 200
    reports = response.json()["reports"]
    assert len(reports) == 25
    assert {report["bank_id"] for report in reports} == {
        "amen_bank",
        "attijari_bank",
        "biat",
        "bt",
        "zitouna",
    }
    assert {report["year"] for report in reports} == {2021, 2022, 2023, 2024, 2025}


def test_complete_request_can_proceed_with_sources() -> None:
    response = client.post(
        "/api/requests/assess",
        json={"message": "Quel est le total des actifs de BIAT en 2023 ?"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["decision"] == "answer"
    assert body["detected_metric"] == "total_assets"
    assert body["sources"] == [
        {
            "bank_id": "biat",
            "bank_name": "BIAT",
            "year": 2023,
            "path": "data/raw/official-reports/etat financier/biat/biat_efd311223.pdf",
            "source_type": "annual_financial_statement",
        }
    ]


def test_metric_catalog_drives_supported_direct_statement_intent() -> None:
    response = client.post(
        "/api/requests/assess",
        json={"message": "Quel est le PNB de BIAT en 2023 ?"},
    )

    body = response.json()
    assert body["decision"] == "answer"
    assert body["detected_metric"] == "net_banking_income"


def test_catalog_drives_all_approved_reported_metric_intents() -> None:
    response = client.post(
        "/api/requests/assess",
        json={"message": "Quels sont les dépôts à vue de BIAT en 2025 ?"},
    )

    assert response.status_code == 200
    assert response.json()["detected_metric"] == "demand_deposits"


def test_reported_answer_includes_the_pdf_page_and_excerpt() -> None:
    response = client.post(
        "/api/requests/answer",
        json={"message": "Quel est le PNB de BIAT en 2025 ?"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["metric_id"] == "net_banking_income"
    assert body["value"] == "1594799"
    assert body["page_number"] == 4
    assert "Produit Net Bancaire" in body["source_excerpt"]


def test_ambiguous_request_requires_precise_clarification() -> None:
    response = client.post("/api/requests/assess", json={"message": "Quelle banque est meilleure ?"})

    body = response.json()
    assert body["decision"] == "clarify"
    assert body["missing_information"] == [
        "banque a analyser",
        "annee ou periode",
        "indicateur financier a analyser",
    ]


def test_request_with_only_a_missing_year_explains_how_to_complete_it() -> None:
    response = client.post("/api/requests/assess", json={"message": "Quel est le PNB de BIAT ?"})

    body = response.json()
    assert body["decision"] == "clarify"
    assert body["missing_information"] == ["annee ou periode"]
    assert "provide the relevant year" in body["reason"]


def test_missing_report_must_not_be_invented() -> None:
    response = client.post(
        "/api/requests/assess",
        json={"message": "Quel est le resultat net de BIAT en 2020 ?"},
    )

    body = response.json()
    assert body["decision"] == "abstain"
    assert body["sources"] == []


def test_conversation_engine_keeps_the_documentary_dossier_for_a_short_follow_up(monkeypatch) -> None:
    received_queries: list[str] = []

    def fake_answer(question, evidence):
        received_queries.append(question)
        return "Analyse documentaire testée [p. 38]"

    monkeypatch.setattr(dialogue, "answer_from_evidence", fake_answer)
    first = client.post(
        "/api/conversation/answer",
        json={"message": "Transactions avec les parties liées de BIAT en 2021", "context": {}},
    )

    assert first.status_code == 200
    assert first.json()["type"] == "document"
    context = first.json()["context"]

    follow_up = client.post(
        "/api/conversation/answer",
        json={"message": "Que signifie ce contrat ?", "context": context},
    )

    assert follow_up.status_code == 200
    assert follow_up.json()["type"] == "document"
    assert follow_up.json()["context"]["bank_id"] == "biat"
    assert follow_up.json()["context"]["reporting_year"] == 2021
    assert "about Transactions avec les parties liées" in received_queries[-1]


def test_conversation_engine_uses_the_catalog_only_for_a_confirmed_metric() -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": "Quel est le PNB de BIAT en 2025 ?", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "numeric"
    assert response.json()["metric_id"] == "net_banking_income"


def test_comparison_uses_each_named_bank_and_the_year_from_the_metric_context() -> None:
    first = client.post(
        "/api/conversation/answer",
        json={"message": "What's the PNB of BIAT in 2025?", "context": {}},
    )
    response = client.post(
        "/api/conversation/answer",
        json={"message": "Can you compare the PNB of BIAT and Zitouna?", "context": first.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "comparison"
    assert response.json()["metric_id"] == "net_banking_income"
    assert response.json()["reporting_year"] == 2025
    assert response.json()["context"]["mode"] == "comparison"
    assert response.json()["context"]["comparison_bank_ids"] == ["biat", "zitouna"]
    assert [(item["bank_name"], item["value"], item["page_number"]) for item in response.json()["values"]] == [
        ("BIAT", "1594799", 4),
        ("Banque Zitouna", "450885", 4),
    ]


def test_all_banks_follow_up_expands_an_active_comparison_instead_of_analysing_it(monkeypatch) -> None:
    comparison = client.post(
        "/api/conversation/answer",
        json={"message": "Compare the net banking income in 2025 of BIAT, BT and Zitouna", "context": {}},
    )
    monkeypatch.setattr(dialogue, "_classify_conversation_intent", lambda *args, **kwargs: {
        "operation": "compare", "bank_scope": "all_available", "period_scope": "active",
        "metric_scope": "active", "document_action": "new", "clarification": "",
    })
    response = client.post(
        "/api/conversation/answer",
        json={"message": "now alll the banks available", "context": comparison.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "comparison"
    assert [item["bank_name"] for item in response.json()["values"]] == [
        "Amen Bank",
        "Attijari Bank",
        "BIAT",
        "Banque de Tunisie",
        "Banque Zitouna",
    ]


def test_all_banks_request_keeps_a_comparison_dossier_until_the_year_and_metric_are_supplied(monkeypatch) -> None:
    def all_banks_plan(message, *args, **kwargs):
        if "all" in message:
            return {
                "operation": "compare", "bank_scope": "all_available", "period_scope": "active",
                "metric_scope": "active", "document_action": "new", "clarification": "",
            }
        return {
            "operation": "compare", "bank_scope": "active_comparison", "period_scope": "explicit",
            "metric_scope": "explicit", "document_action": "new", "clarification": "",
        }

    monkeypatch.setattr(dialogue, "_classify_conversation_intent", all_banks_plan)
    requested = client.post(
        "/api/conversation/answer",
        json={"message": "can you compare all the banks", "context": {}},
    )
    response = client.post(
        "/api/conversation/answer",
        json={"message": "net banking income in 2025", "context": requested.json()["context"]},
    )

    assert requested.status_code == 200
    assert requested.json()["type"] == "clarification"
    assert requested.json()["context"]["comparison_bank_ids"] == [
        "amen_bank",
        "attijari_bank",
        "biat",
        "bt",
        "zitouna",
    ]
    assert response.status_code == 200
    assert response.json()["type"] == "comparison"
    assert len(response.json()["values"]) == 5


def test_a_year_follow_up_completes_an_incomplete_all_banks_comparison(monkeypatch) -> None:
    def plan(message, *args, **kwargs):
        if message == "in 2025":
            # Reproduce the general planner's incorrect attempt to analyse an
            # incomplete comparison; the state validator must repair it.
            return {"operation": "comparison_analysis", "bank_scope": "none", "period_scope": "explicit", "metric_scope": "active"}
        return {"operation": "compare", "bank_scope": "all_available", "period_scope": "active", "metric_scope": "explicit"}

    monkeypatch.setattr(dialogue, "_classify_conversation_intent", plan)
    requested = client.post(
        "/api/conversation/answer",
        json={"message": "compare the net banking income of all banks", "context": {}},
    )
    response = client.post(
        "/api/conversation/answer",
        json={"message": "in 2025", "context": requested.json()["context"]},
    )

    assert requested.json()["type"] == "clarification"
    assert response.status_code == 200
    assert response.json()["type"] == "comparison"
    assert response.json()["reporting_year"] == 2025
    assert len(response.json()["values"]) == 5


def test_multi_metric_analysis_uses_the_metrics_retained_by_one_comparison(monkeypatch) -> None:
    def plan(message, *args, **kwargs):
        if "all the metrics" in message:
            # The general planner may call it an ordinary analysis; the
            # independent analysis-scope decision protects the full history.
            return {"operation": "comparison_analysis", "bank_scope": "active_comparison", "period_scope": "active", "metric_scope": "active"}
        return {"operation": "compare", "bank_scope": "all_available" if "all banks" in message else "active_comparison", "period_scope": "explicit" if "2025" in message else "active", "metric_scope": "explicit"}

    monkeypatch.setattr(dialogue, "_classify_conversation_intent", plan)
    monkeypatch.setattr(
        dialogue,
        "_classify_requested_analysis_scope",
        lambda message, context: "all_discussed_metrics" if "all the metrics" in message else None,
    )
    pnb = client.post(
        "/api/conversation/answer",
        json={"message": "compare the net banking income in 2025 of all banks", "context": {}},
    )
    deposits = client.post(
        "/api/conversation/answer",
        json={"message": "what about the demand deposits", "context": pnb.json()["context"]},
    )
    income = client.post(
        "/api/conversation/answer",
        json={"message": "and the net income", "context": deposits.json()["context"]},
    )
    response = client.post(
        "/api/conversation/answer",
        json={"message": "I want a detailed analysis of all the metrics we talked about", "context": income.json()["context"]},
    )

    assert income.json()["context"]["comparison_metric_ids"] == [
        "net_banking_income", "demand_deposits", "net_income",
    ]
    assert response.status_code == 200
    assert response.json()["type"] == "multi_metric_comparison_analysis"
    assert [item["metric_id"] for item in response.json()["metrics"]] == [
        "net_banking_income", "demand_deposits", "net_income",
    ]


def test_comparison_accepts_uniquely_matched_note_values_outside_auto_validation() -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": "Compare the demand deposits of Zitouna and BIAT in 2025", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "comparison"
    assert response.json()["metric_id"] == "demand_deposits"
    assert [(item["bank_name"], item["value"], item["page_number"]) for item in response.json()["values"]] == [
        ("BIAT", "10674008", 21),
        ("Banque Zitouna", "1737288", 36),
    ]


def test_comparison_follow_up_routes_to_comparative_report_analysis(monkeypatch) -> None:
    first = client.post(
        "/api/conversation/answer",
        json={"message": "What was BIAT's net banking income in 2021?", "context": {}},
    )
    comparison = client.post(
        "/api/conversation/answer",
        json={"message": "Compare the net banking income of BIAT and Zitouna", "context": first.json()["context"]},
    )
    received: dict[str, object] = {}
    monkeypatch.setattr(dialogue, "_classify_conversation_intent", lambda *args, **kwargs: {"intent": "comparison_analysis", "clarification": ""})

    def comparison_analysis(message, context):
        received["message"] = message
        received["context"] = context
        return {
            "type": "comparison_analysis",
            "mode": "comparison",
            "context": context.model_dump(),
            "metric_id": context.metric_id,
            "reporting_year": context.reporting_year,
            "answer": "Source-grounded comparative analysis.",
            "values": [],
            "evidence": [],
            "analysis": {},
        }

    monkeypatch.setattr(dialogue, "_comparison_analysis_turn", comparison_analysis)
    response = client.post(
        "/api/conversation/answer",
        json={"message": "Is it normal to have this much difference?", "context": comparison.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "comparison_analysis"
    assert received["message"] == "Is it normal to have this much difference?"
    context = received["context"]
    assert context.comparison_bank_ids == ["biat", "zitouna"]
    assert context.metric_id == "net_banking_income"
    assert context.reporting_year == 2021


def test_comparison_gap_summary_is_readable_and_never_repeats_raw_pdf_excerpts() -> None:
    summary = dialogue._comparison_gap_summary(
        [
            {"bank_name": "BIAT", "value": "10674008", "reporting_year": 2025},
            {"bank_name": "Banque Zitouna", "value": "1737288", "reporting_year": 2025},
        ],
        "",
    )

    assert "8,936,720 thousand TND more" in summary
    assert "about 6.1×" in summary
    assert "Answer based directly" not in summary
    assert "Dépôts à vue" not in summary


def test_comparison_gap_summary_uses_the_metric_being_analysed() -> None:
    summary = dialogue._comparison_gap_summary(
        [
            {"bank_name": "BIAT", "value": "1594799", "reporting_year": 2025},
            {"bank_name": "Banque Zitouna", "value": "450885", "reporting_year": 2025},
        ],
        metric_id="net_banking_income",
    )

    assert "net banking income" in summary
    assert "demand deposits" not in summary


def test_multi_bank_comparison_summary_keeps_every_bank_in_its_reading() -> None:
    summary = dialogue._comparison_gap_summary(
        [
            {"bank_name": "Amen Bank", "value": "590069", "reporting_year": 2025},
            {"bank_name": "Attijari Bank", "value": "709632", "reporting_year": 2025},
            {"bank_name": "BIAT", "value": "1594799", "reporting_year": 2025},
            {"bank_name": "Banque de Tunisie", "value": "531686", "reporting_year": 2025},
            {"bank_name": "Banque Zitouna", "value": "450885", "reporting_year": 2025},
        ],
        metric_id="net_banking_income",
    )

    assert "reported ranking" in summary
    assert all(name in summary for name in ("Amen Bank", "Attijari Bank", "BIAT", "Banque de Tunisie", "Banque Zitouna"))
    assert "1,143,914 thousand TND" in summary


def test_comparison_analysis_replaces_the_documentary_raw_excerpt_fallback(monkeypatch) -> None:
    comparison = client.post(
        "/api/conversation/answer",
        json={"message": "Compare the demand deposits of BIAT and Zitouna in 2025", "context": {}},
    )
    monkeypatch.setattr(
        dialogue,
        "answer_from_evidence",
        lambda *args, **kwargs: "Answer based directly on the most relevant report excerpts:\n\n- « raw PDF table » [p. 21]",
    )

    response = client.post(
        "/api/conversation/answer",
        json={"message": "The numbers are so different", "context": comparison.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "comparison_analysis"
    assert "8,936,720 thousand TND more" in response.json()["answer"]
    assert "raw PDF table" not in response.json()["answer"]


def test_catalog_metric_outside_the_auto_validated_core_returns_an_exact_source_value() -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": "What is the Résultat d'exploitation of BIAT in 2025?", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "source_value"
    assert response.json()["value"] == "660313"
    assert response.json()["unit_scale"] == "thousand"
    assert response.json()["page_number"] == 4
    assert response.json()["source_label"] == "Résultat d'exploitation"
    assert " ".join(response.json()["source_excerpt"].split()) == "Résultat d'exploitation 660 313 669 616"


def test_financing_cash_flow_uses_the_primary_statement_row_not_a_documentary_cash_note() -> None:
    response = client.post(
        "/api/conversation/answer",
        json={
            "message": "c'est quoi le Flux de trésorerie net provenant des activités de financement de BIAT in 2023",
            "context": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["type"] == "source_value"
    assert response.json()["metric_id"] == "financing_cash_flow"
    assert response.json()["value"] == "-191045"
    assert response.json()["unit_scale"] == "thousand"
    assert response.json()["page_number"] == 5
    assert " ".join(response.json()["source_excerpt"].split()) == (
        "Flux de trésorerie net provenant des activités de financement (191 045) 52 504"
    )


def test_demand_deposits_use_the_declared_note_row_when_pdf_sections_are_unclassified() -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": "What were BIAT's demand deposits in 2025?", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "source_value"
    assert response.json()["value"] == "10674008"
    assert response.json()["unit_scale"] == "thousand"
    assert response.json()["page_number"] == 21
    assert " ".join(response.json()["source_excerpt"].split()) == "Dépôts à vue 10 674 008 10 532 265"


def test_zitouna_demand_deposits_use_its_bank_specific_note_profile() -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": "What were Banque Zitouna's demand deposits in 2025?", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "source_value"
    assert response.json()["value"] == "1737288"
    assert response.json()["page_number"] == 36
    assert " ".join(response.json()["source_excerpt"].split()) == "Comptes à vue (i) 1 737 288 1 535 201 202 088 13"


def test_zitouna_demand_deposits_2021_use_the_deposits_note_not_financing_debt() -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": "What were Banque Zitouna's demand deposits in 2021?", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "source_value"
    assert response.json()["value"] == "1210599"
    assert response.json()["page_number"] == 29
    assert " ".join(response.json()["source_excerpt"].split()) == "Comptes à vue (i) 1 210 599 1 167 820 42 779 3,7"


@pytest.mark.parametrize(
    ("bank_name", "value", "page_number"),
    [
        ("Amen Bank", "2501001", 33),
        ("Attijari Bank", "5385219", 26),
        ("BIAT", "10674008", 21),
        ("Banque de Tunisie", "1835731", 25),
        ("Banque Zitouna", "1737288", 36),
    ],
)
def test_demand_deposits_have_one_declared_source_row_for_every_available_bank_in_2025(
    bank_name: str, value: str, page_number: int
) -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": f"What were {bank_name}'s demand deposits in 2025?", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "source_value"
    assert response.json()["value"] == value
    assert response.json()["page_number"] == page_number


def test_a_bank_substitution_continues_the_active_metric_instead_of_opening_a_profile(monkeypatch) -> None:
    first = client.post(
        "/api/conversation/answer",
        json={"message": "What were BIAT's demand deposits in 2025?", "context": {}},
    )
    # Even an imperfect model classification must not override the explicit
    # conversational form “what about <other bank>?” inside a metric turn.
    monkeypatch.setattr(dialogue, "_classify_conversation_intent", lambda *args, **kwargs: {"intent": "bank_profile", "clarification": ""})

    response = client.post(
        "/api/conversation/answer",
        json={"message": "what about zitouna bank", "context": first.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "source_value"
    assert response.json()["context"]["bank_id"] == "zitouna"
    assert response.json()["context"]["reporting_year"] == 2025
    assert response.json()["context"]["metric_id"] == "demand_deposits"
    assert response.json()["value"] == "1737288"
    assert response.json()["page_number"] == 36


def test_compare_them_uses_the_two_banks_just_discussed_for_the_active_metric(monkeypatch) -> None:
    biat = client.post(
        "/api/conversation/answer",
        json={"message": "What was BIAT's net banking income in 2025?", "context": {}},
    )
    zitouna = client.post(
        "/api/conversation/answer",
        json={"message": "what about zitouna", "context": biat.json()["context"]},
    )
    monkeypatch.setattr(dialogue, "_classify_conversation_intent", lambda *args, **kwargs: {
        "operation": "compare", "bank_scope": "active_pair", "period_scope": "active",
        "metric_scope": "active", "document_action": "new", "document_scope": "none", "clarification": "",
    })
    response = client.post(
        "/api/conversation/answer",
        json={"message": "compare them", "context": zitouna.json()["context"]},
    )

    assert zitouna.json()["context"]["metric_bank_ids"] == ["biat", "zitouna"]
    assert response.status_code == 200
    assert response.json()["type"] == "comparison"
    assert [(item["bank_name"], item["value"]) for item in response.json()["values"]] == [
        ("BIAT", "1594799"),
        ("Banque Zitouna", "450885"),
    ]


def test_normality_follow_up_uses_year_on_year_context_instead_of_repeating_the_metric(monkeypatch) -> None:
    first = client.post(
        "/api/conversation/answer",
        json={"message": "What was BIAT's net income in 2024?", "context": {}},
    )
    monkeypatch.setattr(dialogue, "_classify_conversation_intent", lambda *args, **kwargs: {"intent": "metric_interpretation", "clarification": ""})
    response = client.post(
        "/api/conversation/answer",
        json={"message": "is it normal", "context": first.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "metric_analysis"
    assert "Compared with 2023" in response.json()["answer"]
    assert "26,310 thousand TND (7.9%)" in response.json()["answer"]
    assert "not enough on its own to conclude whether the result is normal" in response.json()["answer"]


def test_semantic_router_can_request_metric_interpretation_beyond_the_normality_phrase(monkeypatch) -> None:
    first = client.post(
        "/api/conversation/answer",
        json={"message": "What was BIAT's net income in 2024?", "context": {}},
    )
    monkeypatch.setattr(
        dialogue,
        "_classify_conversation_intent",
        lambda *args, **kwargs: {"intent": "metric_interpretation", "clarification": ""},
    )

    response = client.post(
        "/api/conversation/answer",
        json={"message": "How should I read this performance?", "context": first.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "metric_analysis"
    assert "Compared with 2023" in response.json()["answer"]


@pytest.mark.parametrize(
    "bank_name",
    ["Amen Bank", "Attijari Bank", "BIAT", "Banque de Tunisie", "Banque Zitouna"],
)
def test_bank_identity_questions_use_each_bank_official_title_page(bank_name: str) -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": f"What is {bank_name}?", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "document"
    assert response.json()["analysis"]["intent"] == "bank_identification"
    assert response.json()["evidence"][0]["page_number"] == 1


def test_bank_identity_question_uses_an_official_title_page_after_a_metric_turn() -> None:
    metric_turn = client.post(
        "/api/conversation/answer",
        json={"message": "What was BIAT's net banking income in 2025?", "context": {}},
    )

    response = client.post(
        "/api/conversation/answer",
        json={"message": "What is BIAT?", "context": metric_turn.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "document"
    assert "banque internationale arabe de tunisie" in response.json()["answer"].lower()
    assert response.json()["evidence"][0]["page_number"] == 1


def test_bank_identity_question_tolerates_a_missing_space_before_the_alias() -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": "What isBIAT?", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "document"
    assert response.json()["context"]["bank_id"] == "biat"


def test_bank_identity_question_accepts_the_common_whats_contraction() -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": "what's biat?", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "document"
    assert response.json()["context"]["bank_id"] == "biat"


@pytest.mark.parametrize(
    "question",
    [
        "whta is a financial repport",
        "what does official report mean?",
        "Qu'est-ce qu'un rapport financier ?",
        "in general",
    ],
)
def test_general_education_questions_use_the_conversation_agent_not_a_static_keyword_reply(monkeypatch, question: str) -> None:
    monkeypatch.setattr(dialogue, "_classify_conversation_intent", lambda *args, **kwargs: {"intent": "general_education", "clarification": ""})
    monkeypatch.setattr(dialogue, "complete", lambda *args, **kwargs: "A tailored explanation generated for this general question.")
    identity = client.post(
        "/api/conversation/answer",
        json={"message": "What is BIAT?", "context": {}},
    )

    response = client.post(
        "/api/conversation/answer",
        json={"message": question, "context": identity.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "general"
    assert response.json()["topic"] == "general_education"
    assert response.json()["answer"] == "A tailored explanation generated for this general question."
    assert response.json()["context"]["mode"] == "general"
    assert response.json()["context"]["bank_id"] is None
    assert response.json()["context"]["reporting_year"] is None


def test_a_question_mentioning_financial_report_can_still_route_to_documents(monkeypatch) -> None:
    monkeypatch.setattr(dialogue, "_classify_conversation_intent", lambda *args, **kwargs: {"intent": "documentary", "clarification": ""})
    monkeypatch.setattr(dialogue, "answer_from_evidence", lambda question, evidence: "Grounded documentary answer [p. 12]")

    response = client.post(
        "/api/conversation/answer",
        json={"message": "What does BIAT's financial report say about credit risk in 2025?", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "document"
    assert response.json()["context"]["bank_id"] == "biat"
    assert response.json()["context"]["reporting_year"] == 2025


def test_general_question_replaces_an_inherited_metric_context(monkeypatch) -> None:
    metric_turn = client.post(
        "/api/conversation/answer",
        json={"message": "What was BIAT's net banking income in 2025?", "context": {}},
    )
    monkeypatch.setattr(dialogue, "_classify_conversation_intent", lambda *args, **kwargs: {"intent": "general_education", "clarification": ""})
    monkeypatch.setattr(dialogue, "complete", lambda *args, **kwargs: "A financial report is explained here as a general concept.")

    response = client.post(
        "/api/conversation/answer",
        json={"message": "what is a financial report?", "context": metric_turn.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "general"
    assert response.json()["context"]["mode"] == "general"
    assert response.json()["answer"] == "A financial report is explained here as a general concept."


def test_general_follow_up_keeps_the_general_conversation_without_a_bank_or_metric(monkeypatch) -> None:
    prompts: list[str] = []
    monkeypatch.setattr(dialogue, "_classify_conversation_intent", lambda *args, **kwargs: {"intent": "general_education", "clarification": ""})
    monkeypatch.setattr(dialogue, "complete", lambda *args, **kwargs: "A first general explanation about financial reports.")
    first = client.post(
        "/api/conversation/answer",
        json={"message": "what is a financial report?", "context": {}},
    )
    monkeypatch.setattr(dialogue, "_classify_conversation_intent", lambda *args, **kwargs: None)

    def continued_answer(prompt: str, **kwargs) -> str:
        prompts.append(prompt)
        return "No, banks are not the only organisations that prepare financial reports."

    monkeypatch.setattr(dialogue, "complete", continued_answer)

    response = client.post(
        "/api/conversation/answer",
        json={"message": "only banks are supposed to do this report?", "context": first.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "general"
    assert response.json()["context"]["mode"] == "general"
    assert response.json()["answer"].startswith("No, banks are not")
    assert "General conversation topic:\nwhat is a financial report" in prompts[0]
    assert "Previous answer:\nA first general explanation about financial reports." in prompts[0]


@pytest.mark.parametrize("question", ["describe BIAT", "tell me about BIAT", "BIAT?"])
def test_bank_profile_routing_does_not_depend_on_a_fixed_question_expression(question: str) -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": question, "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "document"
    assert response.json()["context"]["bank_id"] == "biat"


def test_a_bank_question_with_a_subject_routes_to_documents_not_the_profile_shortcut() -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": "BIAT credit risk", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "clarification"
    assert response.json()["mode"] == "document"
    assert response.json()["missing_information"] == ["reporting year or period"]


def test_source_query_with_bank_and_year_is_not_limited_to_predefined_intents() -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": "BIAT 2025 normes comptables", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "document"
    assert response.json()["evidence"][0]["page_number"] == 6


def test_documentary_follow_up_expands_to_other_related_conventions(monkeypatch) -> None:
    monkeypatch.setattr(dialogue, "answer_from_evidence", lambda question, evidence: "Analyse test [p. 38]")
    first = client.post(
        "/api/conversation/answer",
        json={"message": "Transactions avec les parties liées de BIAT en 2021", "context": {}},
    )
    monkeypatch.setattr(dialogue, "_classify_conversation_intent", lambda *args, **kwargs: {
        "operation": "documentary", "bank_scope": "active_metric", "period_scope": "active",
        "metric_scope": "none", "document_action": "expand_scope",
        "document_scope": "related_party_transactions", "clarification": "",
    })
    response = client.post(
        "/api/conversation/answer",
        json={"message": "Y a-t-il d'autres transactions ?", "context": first.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "document"
    assert any(item["page_number"] == 117 for item in response.json()["evidence"])
    assert response.json()["answer"].startswith("Yes.")
    analysis = response.json()["analysis"]
    assert analysis["intent"] == "scope_expansion"
    assert analysis["scope_label"] == "Auditors’ special report"
    assert "are not interchangeable" in analysis["scope_explanation"]
    assert any(item["title"] == "Scope of the statement" and item["pages"] == [117] for item in analysis["findings"])


def test_related_convention_analysis_uses_only_the_retrieved_context() -> None:
    evidence = [
        type("Evidence", (), {"page_number": 12, "text": "Transaction initiale avec ACME."})(),
        type("Evidence", (), {"page_number": 34, "text": "Convention examinée par les commissaires."})(),
        type(
            "Evidence",
            (),
            {
                "page_number": 56,
                "text": "Nos travaux n'ont pas révélé d'autres conventions ou opérations.",
            },
        )(),
    ]

    analysis = dialogue._related_conventions_analysis(evidence, anchor="ACME")

    assert "GSM" not in analysis["direct_answer"]
    assert "BIAT" not in analysis["direct_answer"]
    assert "[p. 12] [p. 34] [p. 56]" in analysis["direct_answer"]
    assert analysis["findings"][0]["pages"] == [12]
    assert analysis["findings"][1]["pages"] == [34, 56]
    assert analysis["findings"][2]["pages"] == [56]


def test_gsm_anchor_resolves_after_bank_and_year_without_broad_keyword_fallback(monkeypatch) -> None:
    monkeypatch.setattr(dialogue, "answer_from_evidence", lambda question, evidence: "Analyse test [p. 38]")
    def related_conventions_plan(message, *args, **kwargs):
        explicit_bank_and_year = "BIAT 2021" in message
        return {
            "operation": "documentary",
            "bank_scope": "explicit" if explicit_bank_and_year else "active_metric" if "Y a t-il" in message else "none",
            "period_scope": "explicit" if explicit_bank_and_year else "active",
            "metric_scope": "none",
            "document_action": "expand_scope" if explicit_bank_and_year or "Y a t-il" in message else "new",
            "document_scope": "related_party_transactions",
            "clarification": "",
        }

    monkeypatch.setattr(dialogue, "_classify_conversation_intent", related_conventions_plan)
    pending = client.post(
        "/api/conversation/answer",
        json={"message": "Quelles sont les autres conventions après GSM ?", "context": {}},
    )
    assert pending.status_code == 200
    assert pending.json()["type"] == "clarification"
    assert pending.json()["normalization"]["corrections"] == []

    defined = client.post(
        "/api/conversation/answer",
        json={"message": "BIAT 2021", "context": pending.json()["context"]},
    )
    assert defined.status_code == 200
    assert defined.json()["context"]["document_scope"] == "related_party_transactions"
    assert defined.json()["context"]["document_anchor"] == "GSM"
    assert defined.json()["analysis"]["intent"] == "scope_expansion"
    pages_after_completion = {item["page_number"] for item in defined.json()["evidence"]}
    assert {38, 111, 117}.issubset(pages_after_completion)
    assert 7 not in pages_after_completion and 16 not in pages_after_completion and 27 not in pages_after_completion and 80 not in pages_after_completion

    follow_up = client.post(
        "/api/conversation/answer",
        json={"message": "Y a t-il d'autre transactions ?", "context": defined.json()["context"]},
    )
    assert follow_up.status_code == 200
    pages = {item["page_number"] for item in follow_up.json()["evidence"]}
    assert {38, 111, 117}.issubset(pages)
    assert 7 not in pages and 16 not in pages and 37 not in pages
    assert follow_up.json()["analysis"]["intent"] == "scope_expansion"
from types import SimpleNamespace
