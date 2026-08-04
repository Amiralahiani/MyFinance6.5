from myfinance_agent_docs.catalog import load_catalog
from myfinance_agent_docs.corpus import (
    _neighbouring_context,
    retrieve_evidence,
    retrieve_related_conventions,
)
from myfinance_agent_docs.facts import extract_candidate_facts
from myfinance_agent_docs.ingestion import classify_section, ingest_report
from myfinance_contracts import EvidenceChunk
from myfinance_orchestrator.ollama import (
    _relevant_excerpt,
    _safe_qualitative_analysis,
    _source_reading,
    _validated_claim_synthesis,
)


def test_section_classifier_recognises_core_financial_statements() -> None:
    assert classify_section("BILAN\nArrêté au 31 décembre 2023") == "balance_sheet"
    assert classify_section("ETAT DE RESULTAT\nExercice 2023") == "income_statement"
    assert classify_section("ETAT DE FLUX DE TRESORERIE") == "cash_flow_statement"
    assert classify_section("ETAT DES ENGAGEMENTS HORS BILAN") == "off_balance_sheet"


def test_biat_2023_is_extracted_as_traceable_page_chunks() -> None:
    report = next(
        item for item in load_catalog() if item.bank_id == "biat" and item.year == 2023
    )

    ingested = ingest_report(report)

    assert ingested.document.page_count == 84
    assert len(ingested.document.sha256) == 64
    assert any(chunk.page_number == 2 and chunk.section == "balance_sheet" for chunk in ingested.chunks)
    assert any(chunk.page_number == 4 and chunk.section == "income_statement" for chunk in ingested.chunks)
    assert all(chunk.source_path == report.path for chunk in ingested.chunks)
    assert all(chunk.source_sha256 == ingested.document.sha256 for chunk in ingested.chunks)


def test_biat_2023_financial_candidates_remain_unverified_and_traceable() -> None:
    report = next(
        item for item in load_catalog() if item.bank_id == "biat" and item.year == 2023
    )

    facts = {fact.metric_id: fact for fact in extract_candidate_facts(report)}

    assert facts["total_assets"].value == 22_944_526
    assert facts["total_assets"].page_number == 2
    assert facts["net_income"].value == 331_444
    assert facts["net_income"].page_number == 4
    assert facts["customer_loans_net"].value == 12_442_378
    assert facts["customer_deposits"].value == 18_802_457
    assert facts["net_banking_income"].value == 1_396_872
    assert all(fact.unit_scale == "thousand" for fact in facts.values())
    assert all(fact.validation_status == "candidate" for fact in facts.values())


def test_credit_risk_query_prefers_credit_risk_notes_over_governance_mentions() -> None:
    evidence = retrieve_evidence(
        "biat",
        2024,
        "Comment BIAT décrit-elle les risques de crédit en 2024 ?",
        limit=2,
    )

    assert [chunk.page_number for chunk in evidence] == [13, 7]
    assert all("conseil d'administration" not in chunk.text.lower() for chunk in evidence)


def test_document_excerpt_centers_on_the_requested_note() -> None:
    evidence = retrieve_evidence(
        "biat",
        2021,
        "Explique le portefeuille d'encaissement de BIAT en 2021",
        limit=1,
    )

    excerpt = _relevant_excerpt(evidence[0].text, "portefeuille encaissement", 620)
    assert excerpt.startswith("NOTE VIII – Portefeuille d’encaissement")


def test_note_title_matching_tolerates_one_typo_when_other_title_terms_anchor_it() -> None:
    evidence = retrieve_evidence(
        "biat",
        2021,
        "Explique le potfeuille d'encaissement de BIAT en 2021",
        limit=1,
    )

    assert evidence[0].page_number == 36


def test_continuation_context_adds_only_an_adjacent_page_without_a_new_heading() -> None:
    def chunk(page: int, text: str) -> EvidenceChunk:
        return EvidenceChunk(
            chunk_id=f"test-p{page}-c1",
            document_id="test-document",
            bank_id="biat",
            bank_name="BIAT",
            reporting_year=2021,
            page_number=page,
            section="notes",
            source_path="test.pdf",
            source_sha256="a" * 64,
            text=text,
        )

    source = chunk(20, "Note XII – Risque de crédit\nLe tableau se présente comme suit :")
    continuation = chunk(21, "Classe de risque  Encours  Provision\nCourante  100  2")
    next_note = chunk(22, "Note XIII – Portefeuille d'investissement\nPrésentation de la note suivante.")

    context = _neighbouring_context([source, continuation, next_note], [source], slots=2)

    assert [item.page_number for item in context] == [21]


def test_related_party_query_prefers_the_matching_note_title() -> None:
    evidence = retrieve_evidence(
        "biat",
        2021,
        "C'est quoi les transactions avec les parties liées de BIAT en 2021 ?",
        limit=1,
    )

    assert evidence[0].page_number == 38
    assert evidence[0].text.startswith("Note X – Transactions avec les parties liées")


def test_qualitative_analysis_keeps_grounded_explanation_and_drops_numeric_tail() -> None:
    class Source:
        page_number = 38

    answer = (
        "La relation décrite prend la forme d’un bail entre la BIAT et GSM, "
        "avec une composante fixe et une composante variable. [p. 38] "
        "Le contrat prévoit une hausse de 5 % après une période donnée. [p. 38]"
    )

    safe = _safe_qualitative_analysis(answer, [Source()])

    assert "bail entre la BIAT et GSM" in safe
    assert "5 %" not in safe
    assert safe.endswith("[p. 38]")


def test_model_synthesis_requires_an_exact_quote_and_rejects_new_claim_words() -> None:
    evidence = retrieve_evidence(
        "biat", 2021, "Explique le portefeuille d’encaissement de BIAT en 2021", limit=1
    )
    quote = (
        "NOTE VIII – Portefeuille d’encaissement La valeur des chèques, effets et autres valeurs "
        "assimilées détenus par la banque pour le compte de tiers, en attente d’encaissement"
    )
    accepted = _validated_claim_synthesis(
        '{"claims":[{"summary":"Le portefeuille d’encaissement regroupe les chèques, effets et autres valeurs détenus par la banque pour le compte de tiers en attente d’encaissement.",'
        f'"evidence_quote":"{quote}","page":36}}]}}',
        evidence,
    )
    invented = _validated_claim_synthesis(
        '{"claims":[{"summary":"Le portefeuille d’encaissement réduit fortement le risque de la banque.",'
        f'"evidence_quote":"{quote}","page":36}}]}}',
        evidence,
    )

    assert accepted.endswith("[p. 36]")
    assert invented == ""


def test_model_synthesis_rejects_a_quote_not_present_on_the_cited_page() -> None:
    evidence = retrieve_evidence(
        "biat", 2021, "Explique le portefeuille d’encaissement de BIAT en 2021", limit=1
    )
    answer = _validated_claim_synthesis(
        '{"claims":[{"summary":"Le portefeuille est présenté séparément des actifs.",'
        '"evidence_quote":"Cette phrase n’existe pas dans le rapport officiel.","page":36}]}',
        evidence,
    )

    assert answer == ""


def test_source_reading_explains_related_party_note_without_copying_its_figures() -> None:
    evidence = retrieve_evidence(
        "biat",
        2021,
        "Explique les transactions avec les parties liées de BIAT en 2021",
        limit=1,
    )

    reading = _source_reading("Explique les transactions avec les parties liées de BIAT en 2021", evidence)

    assert "relationship with GSM" in reading
    assert "lease of a golf course" in reading
    assert "200.000" not in reading
    assert reading.endswith("[p. 38]")


def test_source_reading_explains_the_portfolio_collection_mechanism() -> None:
    evidence = retrieve_evidence(
        "biat", 2021, "Explique le portefeuille d’encaissement de BIAT en 2021", limit=1
    )

    reading = _source_reading("Explique le portefeuille d’encaissement de BIAT en 2021", evidence)

    assert "on behalf of third parties" in reading
    assert "presented on the balance sheet" in reading
    assert reading.endswith("[p. 36]")


def test_source_reading_explains_cash_flow_note_content() -> None:
    evidence = retrieve_evidence(
        "biat", 2021, "Que dit BIAT de l’état de flux de trésorerie en 2021 ?", limit=1
    )

    reading = _source_reading("Que dit BIAT de l’état de flux de trésorerie en 2021 ?", evidence)

    assert "exchange-rate movements" in reading
    assert "cash and cash equivalents" in reading
    assert reading.endswith("[p. 37]")


def test_related_convention_expansion_reaches_the_auditors_conclusion() -> None:
    evidence = retrieve_related_conventions("biat", 2021)

    pages = {chunk.page_number for chunk in evidence}

    assert 117 in pages
    assert pages.intersection({112, 113, 114})
