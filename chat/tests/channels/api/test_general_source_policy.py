import pytest
from myfinance_contracts import ConversationContext
from myfinance_orchestrator import dialogue
from myfinance_orchestrator.general_sources import sources_for_general_question


def test_current_country_has_priority_over_the_previous_general_topic() -> None:
    sources = sources_for_general_question("and in France", "the main stock-market index in Tunisia")

    assert [source["source_id"] for source in sources] == ["euronext_cac40"]


@pytest.mark.parametrize(
    ("question", "source_id"),
    [
        ("Quel est l’indice boursier principal aux États-Unis ?", "sp_dow_jones_sp500"),
        ("Quel est l’indice boursier principal au Royaume-Uni ?", "ftse_russell_ftse100"),
        ("Quel est l’indice boursier principal en Allemagne ?", "stoxx_dax"),
        ("Quel est l’indice boursier principal au Japon ?", "nikkei_nikkei225"),
    ],
)
def test_curated_official_index_sources_match_their_country(question: str, source_id: str) -> None:
    sources = sources_for_general_question(question)

    assert [source["source_id"] for source in sources] == [source_id]


def test_registered_index_question_precedes_a_market_agent_route(monkeypatch) -> None:
    monkeypatch.setattr(dialogue, "_classify_agent_route", lambda *args, **kwargs: "market")
    assessment = dialogue.assess_request("Quel est l’indice boursier principal aux États-Unis ?")

    plan = dialogue._turn_plan("Quel est l’indice boursier principal aux États-Unis ?", ConversationContext(), assessment)

    assert plan["operation"] == "general_education"


def test_general_answer_returns_only_a_verified_cited_source(monkeypatch) -> None:
    monkeypatch.setenv("MYFINANCE_REQUIRE_GENERAL_SOURCES", "1")
    monkeypatch.setattr(
        dialogue,
        "complete",
        lambda *args, **kwargs: "France's main stock-market index is CAC 40. [euronext_cac40]",
    )

    result = dialogue._general_education_turn("What is the main stock-market index in France?", ConversationContext())

    assert result["type"] == "general"
    assert result["answer"] == "France's main stock-market index is CAC 40."
    assert [source["source_id"] for source in result["sources"]] == ["euronext_cac40"]


def test_general_answer_rejects_an_uncited_model_response(monkeypatch) -> None:
    monkeypatch.setenv("MYFINANCE_REQUIRE_GENERAL_SOURCES", "1")
    monkeypatch.setattr(dialogue, "complete", lambda *args, **kwargs: "The CAC 40 is France's main index.")

    result = dialogue._general_education_turn("What is the main stock-market index in France?", ConversationContext())

    assert result["type"] == "general"
    assert result["source_status"] == "official_source_required"
    assert result["sources"] == []
