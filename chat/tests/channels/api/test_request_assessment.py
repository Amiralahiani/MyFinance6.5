from fastapi.testclient import TestClient
from myfinance_orchestrator import dialogue
from myfinance_orchestrator.language import correct_financial_spelling
from myfinance_orchestrator.main import app

client = TestClient(app)


def test_financial_spelling_repair_does_not_mutate_an_unanchored_typo() -> None:
    message, corrections = correct_financial_spelling("Explique le potfeuille d'encaissement de BIAT")

    assert message == "Explique le potfeuille d'encaissement de BIAT"
    assert corrections == []


def test_financial_spelling_repair_does_not_replace_valid_document_terms() -> None:
    message, corrections = correct_financial_spelling("Transactions avec les parties liées")

    assert message == "Transactions avec les parties liées"
    assert corrections == []


def test_financial_spelling_repair_never_rewrites_ordinary_french_prose() -> None:
    message, corrections = correct_financial_spelling("Quelles sont les autres conventions après GSM ?")

    assert message == "Quelles sont les autres conventions après GSM ?"
    assert corrections == []


def test_normalize_endpoint_preserves_an_unanchored_word_for_safe_later_matching() -> None:
    response = client.post("/api/requests/normalize", json={"message": "potfeuille d'encaissement"})

    assert response.status_code == 200
    assert response.json()["message"] == "potfeuille d'encaissement"


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
    assert "indiquez l’année" in body["reason"]


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
    assert "à propos de Transactions avec les parties liées" in received_queries[-1]


def test_conversation_engine_uses_the_catalog_only_for_a_confirmed_metric() -> None:
    response = client.post(
        "/api/conversation/answer",
        json={"message": "Quel est le PNB de BIAT en 2025 ?", "context": {}},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "numeric"
    assert response.json()["metric_id"] == "net_banking_income"


def test_documentary_follow_up_expands_to_other_related_conventions(monkeypatch) -> None:
    monkeypatch.setattr(dialogue, "answer_from_evidence", lambda question, evidence: "Analyse test [p. 38]")
    first = client.post(
        "/api/conversation/answer",
        json={"message": "Transactions avec les parties liées de BIAT en 2021", "context": {}},
    )
    response = client.post(
        "/api/conversation/answer",
        json={"message": "Y a-t-il d'autres transactions ?", "context": first.json()["context"]},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "document"
    assert any(item["page_number"] == 117 for item in response.json()["evidence"])
    assert response.json()["answer"].startswith("Oui.")
    analysis = response.json()["analysis"]
    assert analysis["intent"] == "scope_expansion"
    assert analysis["scope_label"] == "Rapport spécial des commissaires aux comptes"
    assert "ne sont pas interchangeables" in analysis["scope_explanation"]
    assert any(item["title"] == "Limite de l’affirmation" and item["pages"] == [117] for item in analysis["findings"])


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
