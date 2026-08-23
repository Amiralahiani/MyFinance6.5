"""Optional Qdrant-backed semantic retrieval for source-preserving evidence chunks.

The vector store is deliberately additive: callers must keep the deterministic
lexical retrieval path and may fall back to it whenever Qdrant or embeddings
are unavailable.  Each vector payload contains the full original chunk, so a
semantic match never loses its bank, year, PDF path or page provenance.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from myfinance_contracts import EvidenceChunk

_POINT_NAMESPACE = uuid.UUID("b14a92e1-daaa-40e3-980b-1cd6a568e760")
_TRUE_VALUES = {"1", "true", "yes", "on"}


class VectorStoreUnavailable(RuntimeError):
    """Raised for an optional vector dependency that cannot safely be used."""


@dataclass(frozen=True)
class VectorStoreSettings:
    qdrant_url: str
    collection: str
    embeddings_url: str
    embedding_model: str
    timeout_seconds: float = 20.0

    @classmethod
    def from_environment(cls) -> VectorStoreSettings:
        try:
            timeout_seconds = float(os.environ.get("MYFINANCE_EMBEDDING_TIMEOUT_SECONDS", "20"))
        except ValueError:
            timeout_seconds = 20.0
        return cls(
            qdrant_url=os.environ.get("MYFINANCE_QDRANT_URL", "http://127.0.0.1:6333").rstrip("/"),
            collection=os.environ.get("MYFINANCE_QDRANT_COLLECTION", "myfinance_evidence"),
            embeddings_url=os.environ.get(
                "MYFINANCE_EMBEDDINGS_URL", "http://127.0.0.1:11434/api/embed"
            ).rstrip("/"),
            embedding_model=os.environ.get("MYFINANCE_EMBEDDING_MODEL", "nomic-embed-text"),
            timeout_seconds=max(timeout_seconds, 1.0),
        )


def vector_retrieval_enabled() -> bool:
    """Return whether semantic retrieval is explicitly enabled for this process."""
    return os.environ.get("MYFINANCE_VECTOR_ENABLED", "0").strip().lower() in _TRUE_VALUES


class QdrantVectorStore:
    """Small standard-library client for the Qdrant operations MyFinance needs."""

    def __init__(self, settings: VectorStoreSettings | None = None) -> None:
        self.settings = settings or VectorStoreSettings.from_environment()

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.settings.qdrant_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                body = response.read()
        except HTTPError as error:
            if error.code == 404:
                return None
            raise VectorStoreUnavailable(f"Qdrant returned HTTP {error.code}.") from error
        except (URLError, TimeoutError, OSError) as error:
            raise VectorStoreUnavailable("Qdrant is unavailable.") from error
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as error:
            raise VectorStoreUnavailable("Qdrant returned invalid JSON.") from error
        return decoded if isinstance(decoded, dict) else {}

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.settings.embedding_model, "input": texts}
        request = Request(
            self.settings.embeddings_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                body = json.loads(response.read())
        except HTTPError as error:
            if len(texts) > 1:
                # Some Ollama releases expose /api/embed but accept one input
                # per request only. Preserve a source chunk unchanged and
                # fall back transparently instead of abandoning the index.
                return [vector for text in texts for vector in self._embed([text])]
            raise VectorStoreUnavailable(
                f"The embeddings service returned HTTP {error.code}."
            ) from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise VectorStoreUnavailable("The embeddings service is unavailable.") from error
        embeddings = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise VectorStoreUnavailable("The embeddings service returned an invalid response.")
        try:
            return [[float(value) for value in vector] for vector in embeddings]
        except (TypeError, ValueError) as error:
            raise VectorStoreUnavailable("The embeddings service returned non-numeric vectors.") from error

    def ensure_collection(self, vector_size: int) -> None:
        path = f"/collections/{self.settings.collection}"
        if self._request_json("GET", path) is not None:
            return
        self._request_json(
            "PUT",
            path,
            {"vectors": {"size": vector_size, "distance": "Cosine"}},
        )

    def index_chunks(self, chunks: list[EvidenceChunk], batch_size: int = 8) -> int:
        """Embed and persist chunks while retaining complete evidence payloads."""
        if not chunks:
            return 0
        indexed = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = self._embed([chunk.text for chunk in batch])
            if not vectors or not vectors[0]:
                raise VectorStoreUnavailable("The embeddings service returned an empty vector.")
            self.ensure_collection(len(vectors[0]))
            points = [
                {
                    "id": str(uuid.uuid5(_POINT_NAMESPACE, chunk.chunk_id)),
                    "vector": vector,
                    "payload": {
                        "bank_id": chunk.bank_id,
                        "reporting_year": chunk.reporting_year,
                        "chunk": chunk.model_dump(mode="json"),
                    },
                }
                for chunk, vector in zip(batch, vectors, strict=True)
            ]
            self._request_json(
                "PUT",
                f"/collections/{self.settings.collection}/points?wait=true",
                {"points": points},
            )
            indexed += len(points)
        return indexed

    def search(self, bank_id: str, year: int, question: str, limit: int = 3) -> list[EvidenceChunk]:
        """Retrieve only chunks scoped to the requested official bank report."""
        vectors = self._embed([question])
        if not vectors or not vectors[0]:
            raise VectorStoreUnavailable("The embeddings service returned an empty query vector.")
        response = self._request_json(
            "POST",
            f"/collections/{self.settings.collection}/points/query",
            {
                "query": vectors[0],
                "limit": limit,
                "with_payload": True,
                "filter": {
                    "must": [
                        {"key": "bank_id", "match": {"value": bank_id}},
                        {"key": "reporting_year", "match": {"value": year}},
                    ]
                },
            },
        )
        result = (response or {}).get("result", {})
        points = result.get("points", []) if isinstance(result, dict) else []
        evidence: list[EvidenceChunk] = []
        for point in points:
            payload = point.get("payload", {}) if isinstance(point, dict) else {}
            stored_chunk = payload.get("chunk") if isinstance(payload, dict) else None
            if not isinstance(stored_chunk, dict):
                continue
            try:
                evidence.append(EvidenceChunk.model_validate(stored_chunk))
            except ValueError:
                continue
        return evidence


def retrieve_vector_evidence(bank_id: str, year: int, question: str, limit: int = 3) -> list[EvidenceChunk]:
    """Fetch semantic candidates only when vector retrieval was enabled explicitly."""
    if not vector_retrieval_enabled():
        return []
    return QdrantVectorStore().search(bank_id, year, question, limit=limit)
