"""Regression tests for the optional Qdrant enrichment layer."""

from __future__ import annotations

from myfinance_agent_docs.corpus import merge_hybrid_evidence
from myfinance_agent_docs.vector_store import QdrantVectorStore, VectorStoreSettings
from myfinance_contracts import EvidenceChunk


def _chunk(chunk_id: str, page: int) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        document_id="biat-2025-document",
        bank_id="biat",
        bank_name="BIAT",
        reporting_year=2025,
        page_number=page,
        section="notes",
        source_path="data/raw/official-reports/etat financier/biat/biat_efd311225.pdf",
        source_sha256="a" * 64,
        text=f"Official evidence {chunk_id}",
    )


def test_hybrid_merge_keeps_exact_lexical_evidence_first() -> None:
    lexical = [_chunk("lexical-strong", 12), _chunk("lexical-tail", 18)]
    vector = [_chunk("semantic-only", 22), _chunk("lexical-tail", 18)]
    merged = merge_hybrid_evidence(lexical, vector, limit=3)
    assert [chunk.chunk_id for chunk in merged] == ["lexical-strong", "lexical-tail", "semantic-only"]


def test_qdrant_index_keeps_full_source_payload(monkeypatch) -> None:
    settings = VectorStoreSettings(
        qdrant_url="http://qdrant:6333",
        collection="test_evidence",
        embeddings_url="http://ollama:11434/api/embed",
        embedding_model="test-embedder",
    )
    store = QdrantVectorStore(settings)
    requests = []
    monkeypatch.setattr(store, "_embed", lambda _texts: [[0.1, 0.2]])
    monkeypatch.setattr(
        store,
        "_request_json",
        lambda method, path, payload=None: requests.append((method, path, payload)) or None,
    )
    assert store.index_chunks([_chunk("evidence-1", 19)]) == 1
    points_payload = requests[-1][2]
    point = points_payload["points"][0]
    assert point["payload"]["bank_id"] == "biat"
    assert point["payload"]["reporting_year"] == 2025
    assert point["payload"]["chunk"]["page_number"] == 19


def test_qdrant_search_scopes_results_to_the_requested_report(monkeypatch) -> None:
    settings = VectorStoreSettings(
        qdrant_url="http://qdrant:6333",
        collection="test_evidence",
        embeddings_url="http://ollama:11434/api/embed",
        embedding_model="test-embedder",
    )
    store = QdrantVectorStore(settings)
    requests = []
    chunk = _chunk("evidence-2", 23)
    monkeypatch.setattr(store, "_embed", lambda _texts: [[0.1, 0.2]])

    def request(method, path, payload=None):
        requests.append((method, path, payload))
        return {"result": {"points": [{"payload": {"chunk": chunk.model_dump(mode="json")}}]}}

    monkeypatch.setattr(store, "_request_json", request)
    assert store.search("biat", 2025, "credit risk", limit=2) == [chunk]
    request_payload = requests[-1][2]
    assert request_payload["filter"]["must"] == [
        {"key": "bank_id", "match": {"value": "biat"}},
        {"key": "reporting_year", "match": {"value": 2025}},
    ]
