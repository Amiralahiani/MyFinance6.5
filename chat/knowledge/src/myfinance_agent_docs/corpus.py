"""Deterministic, source-preserving retrieval over the local report corpus."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter

from myfinance_contracts import EvidenceChunk

from myfinance_agent_docs.catalog import PROJECT_ROOT
from myfinance_agent_docs.section_index import load_section_index

CORPUS_ROOT = PROJECT_ROOT / "data" / "normalized" / "corpus"
STOP_WORDS = {
    "a", "ai", "au", "aux", "avec", "ce", "ces", "comment", "dans", "de", "des", "du",
    "en", "est", "et", "je", "la", "le", "les", "l", "ma", "mes", "par", "pour",
    "pourquoi", "quoi", "quel", "quelle", "quels", "quelles", "sur", "un", "une", "vous",
    "biat", "decrit", "elle", "ils", "leur", "leurs",
}
_NEW_SECTION_HEADING = re.compile(
    r"(?im)^\s*(?:note\s+[ivxlcdm0-9]+\s*[–-]|bilan\b|etat\s+de\s+resultat|"
    r"compte\s+de\s+resultat|etat\s+de\s+flux|etat\s+des\s+engagements)"
)
_NOTE_HEADING = re.compile(r"(?im)^\s*note\s+[ivxlcdm0-9]+\s*[–-]")


def _normalise(value: str) -> str:
    cleaned = "".join(
        character
        for character in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(character) != "Mn"
    )
    return cleaned.replace("’", "'")


def _terms(value: str) -> set[str]:
    return {
        _stem(term) for term in re.findall(r"[a-z]{3,}", _normalise(value))
        if term not in STOP_WORDS and not term.isdigit()
    }


def _stem(term: str) -> str:
    """Light French plural normalisation for deterministic lexical retrieval."""
    return term[:-1] if len(term) > 4 and term.endswith(("s", "x")) else term


def _nearest_distance(words: list[str], first: str, second: str) -> int | None:
    first_positions = [index for index, word in enumerate(words) if word == first]
    second_positions = [index for index, word in enumerate(words) if word == second]
    if not first_positions or not second_positions:
        return None
    return min(abs(left - right) for left in first_positions for right in second_positions)


def _note_heading_terms(text: str) -> set[str]:
    """Extract the title of a financial note when a chunk starts or contains one."""
    match = re.search(r"(?im)^\s*note\s+[ivxlcdm0-9]+\s*[–-]\s*([^\n]+)", text)
    return _terms(match.group(1)) if match else set()


def _single_edit_match(left: str, right: str) -> bool:
    """Allow a close typo only when another title term anchors the match."""
    if len(left) < 6 or left[0] != right[0] or abs(len(left) - len(right)) > 2:
        return False
    previous = list(range(len(right) + 1))
    for index, left_character in enumerate(left, start=1):
        current = [index]
        for other_index, right_character in enumerate(right, start=1):
            current.append(min(current[-1] + 1, previous[other_index] + 1, previous[other_index - 1] + (left_character != right_character)))
        previous = current
    return previous[-1] <= 2


def _is_continuation_page(source: EvidenceChunk, neighbour: EvidenceChunk) -> bool:
    """Recognise a neighbouring page that continues the same note or table.

    Page provenance stays intact.  The neighbour is included only when it does
    not announce another note or financial statement and the selected page has
    a clear note/table continuation signal.
    """
    if abs(source.page_number - neighbour.page_number) != 1:
        return False
    if _NEW_SECTION_HEADING.search(neighbour.text):
        return False
    source_text = _normalise(source.text)
    table_signal = any(
        phrase in source_text
        for phrase in ("se presente comme suit", "le tableau suivant", "reparti comme suit", "ventile comme suit")
    )
    note_signal = bool(_NOTE_HEADING.search(source.text))
    compatible_section = source.section == neighbour.section and source.section != "unclassified"
    return compatible_section or table_signal or note_signal


def _neighbouring_context(
    chunks: list[EvidenceChunk], selected: list[EvidenceChunk], slots: int
) -> list[EvidenceChunk]:
    """Add only safe, adjacent context pages while respecting the result limit."""
    if slots <= 0:
        return []
    by_page: dict[int, list[EvidenceChunk]] = {}
    for chunk in chunks:
        by_page.setdefault(chunk.page_number, []).append(chunk)
    for page_chunks in by_page.values():
        page_chunks.sort(key=lambda chunk: chunk.chunk_id)

    selected_ids = {chunk.chunk_id for chunk in selected}
    context: list[EvidenceChunk] = []
    for source in selected:
        for page in (source.page_number - 1, source.page_number + 1):
            candidates = by_page.get(page, [])
            if not candidates or not _is_continuation_page(source, candidates[0]):
                continue
            for candidate in candidates:
                if candidate.chunk_id not in selected_ids:
                    context.append(candidate)
                    selected_ids.add(candidate.chunk_id)
                    if len(context) >= slots:
                        return context
    return context


def _load_chunks(bank_id: str, year: int) -> list[EvidenceChunk]:
    path = CORPUS_ROOT / bank_id / str(year) / "evidence_chunks.jsonl"
    if not path.exists():
        return []
    return [
        EvidenceChunk.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def load_evidence_chunks(bank_id: str, year: int) -> list[EvidenceChunk]:
    """Load source-preserving chunks for deterministic or vector indexing."""
    return _load_chunks(bank_id, year)


def _retrieve_lexical_evidence(
    bank_id: str,
    year: int,
    question: str,
    limit: int = 3,
    include_related: bool = False,
    include_neighbour_pages: bool = False,
) -> list[EvidenceChunk]:
    """Return the most relevant PDF chunks, preserving their source identity."""
    query_terms = _terms(question)
    requires_credit_risk = {"risque", "credit"}.issubset(query_terms)
    ranked: list[tuple[int, int, EvidenceChunk]] = []
    chunks = _load_chunks(bank_id, year)
    if not chunks:
        return []
    for chunk in chunks:
        normalized = _normalise(chunk.text)
        words = [_stem(term) for term in re.findall(r"[a-z]{3,}", normalized)]
        counts = Counter(words)
        matched_terms = {term for term in query_terms if counts[term]}
        heading_terms = _note_heading_terms(chunk.text)
        heading_overlap = query_terms & heading_terms
        fuzzy_heading_matches = {
            term for term in query_terms - heading_overlap
            if any(_single_edit_match(term, heading_term) for heading_term in heading_terms)
        }
        title_coverage = len(heading_overlap) + len(fuzzy_heading_matches)
        if len(query_terms) > 1 and len(matched_terms) < 2 and title_coverage < 2:
            continue

        score = sum(min(counts[term], 3) for term in query_terms)
        if title_coverage >= 2:
            # A matching note title is a far stronger signal than incidental words
            # in tables or explanatory paragraphs on another subject.
            score += 25 + (5 * title_coverage)
        if requires_credit_risk:
            distance = _nearest_distance(words, "risque", "credit")
            supporting_terms = {"provision", "creance", "classe", "portefeuille", "contrepartie"}
            supporting_score = sum(min(counts[term], 2) for term in supporting_terms)
            if distance is not None and distance <= 6:
                score += 30
            elif distance is not None and distance <= 24:
                score += 12
            elif supporting_score >= 2:
                # A financial-risk section can discuss classification or provisions
                # before mentioning credit again later in the same extracted chunk.
                score += supporting_score
            else:
                # Do not promote unrelated occurrences such as a company named
                # "Capital Risque" on a page that happens to mention credit elsewhere.
                continue
            score += supporting_score
            governance_terms = {"conseil", "administration", "remuneration", "jeton", "directeur"}
            if sum(counts[term] for term in governance_terms) >= 2:
                # A board or remuneration section can name credit and risk committees
                # without describing the bank's credit-risk exposure or methodology.
                score -= 25
        if score > 0:
            ranked.append((score, title_coverage, chunk))
    # When a note title matches the requested subject, its pages are the authoritative
    # context. Do not dilute them with a generic table that merely shares a few words.
    title_matches = [item for item in ranked if item[1] >= 2]
    selected = ranked if include_related else title_matches if title_matches else ranked
    primary_limit = max(1, limit - 1) if include_neighbour_pages and limit > 1 else limit
    primary = [
        chunk
        for _, _, chunk in sorted(selected, key=lambda item: (-item[0], item[2].page_number))[:primary_limit]
    ]
    context = _neighbouring_context(chunks, primary, limit - len(primary)) if include_neighbour_pages else []
    # Keep the highest-ranked passage first; neighbouring context follows it so
    # callers retain the established retrieval order while the model receives
    # the continuation needed to read a split note or table.
    return primary + context


def merge_hybrid_evidence(
    lexical: list[EvidenceChunk], vector: list[EvidenceChunk], limit: int
) -> list[EvidenceChunk]:
    """Fuse lexical and semantic candidates without losing exact-match priority.

    Lexical matches receive twice the rank weight of vector-only matches.  This
    keeps note titles and explicit financial terms authoritative, while still
    allowing a strong semantic result to replace a weak lexical tail.
    """
    scores: dict[str, float] = {}
    chunks: dict[str, EvidenceChunk] = {}
    order: dict[str, int] = {}
    for rank, chunk in enumerate(lexical):
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 2.0 / (rank + 1)
        chunks[chunk.chunk_id] = chunk
        order.setdefault(chunk.chunk_id, rank)
    for rank, chunk in enumerate(vector):
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (rank + 1)
        chunks[chunk.chunk_id] = chunk
        order.setdefault(chunk.chunk_id, len(lexical) + rank)
    ranked_ids = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], order[chunk_id]))
    return [chunks[chunk_id] for chunk_id in ranked_ids[:limit]]


def retrieve_evidence(
    bank_id: str,
    year: int,
    question: str,
    limit: int = 3,
    include_related: bool = False,
    include_neighbour_pages: bool = False,
) -> list[EvidenceChunk]:
    """Retrieve hybrid evidence, safely falling back to deterministic lexical search."""
    lexical = _retrieve_lexical_evidence(
        bank_id,
        year,
        question,
        limit=limit,
        include_related=include_related,
        include_neighbour_pages=include_neighbour_pages,
    )
    try:
        from myfinance_agent_docs.vector_store import (
            VectorStoreUnavailable,
            retrieve_vector_evidence,
            vector_retrieval_enabled,
        )

        if not vector_retrieval_enabled():
            return lexical
        vector = retrieve_vector_evidence(bank_id, year, question, limit=max(limit, 3))
    except VectorStoreUnavailable:
        return lexical
    return merge_hybrid_evidence(lexical, vector, limit)


def retrieve_entity_evidence(bank_id: str, year: int, entity: str, limit: int = 3) -> list[EvidenceChunk]:
    """Resolve a named entity before attempting broad documentary retrieval.

    This is intentionally exact.  A name such as ``GSM`` is an anchor in a
    conversation, not a loose keyword to be mixed with every occurrence of
    “convention” or “liée” in the report.
    """
    path = CORPUS_ROOT / bank_id / str(year) / "evidence_chunks.jsonl"
    if not path.exists() or len(entity.strip()) < 2:
        return []
    expression = re.compile(rf"(?<![A-Za-z0-9]){re.escape(entity.strip())}(?![A-Za-z0-9])", re.IGNORECASE)
    matches = [
        EvidenceChunk.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if expression.search(json.loads(line).get("text", ""))
    ]
    return sorted(matches, key=lambda item: item.page_number)[:limit]


def retrieve_related_conventions(bank_id: str, year: int, limit: int = 6) -> list[EvidenceChunk]:
    """Expand a related-party follow-up to the special-report convention section.

    A question such as “are there others?” cannot be answered from the first note
    alone.  The statutory special report is the proper scope because it lists the
    conventions reviewed by the auditors and closes with their completeness statement.
    """
    path = CORPUS_ROOT / bank_id / str(year) / "evidence_chunks.jsonl"
    if not path.exists():
        return []
    chunks = [EvidenceChunk.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]
    section_index = load_section_index(bank_id, year)
    special_start = section_index["special_audit_report"]["start_page"]
    conclusion_page = section_index["special_audit_report"]["conclusion_page"]
    if special_start is None:
        return []
    first_special_page = special_start
    def compact(chunk: EvidenceChunk) -> str:
        return " ".join(_normalise(chunk.text).split())

    if conclusion_page is not None:
        detailed_section = [
            chunk
            for chunk in chunks
            if max(first_special_page, conclusion_page - 6) <= chunk.page_number <= conclusion_page
            and re.search(r"\b(convention|conventions|contrat|contrats|operation|operations)\b", compact(chunk))
        ]
        if detailed_section:
            unique_pages: dict[int, EvidenceChunk] = {}
            for chunk in sorted(detailed_section, key=lambda item: item.page_number):
                unique_pages.setdefault(chunk.page_number, chunk)
            conclusion = unique_pages.get(conclusion_page)
            leading = [chunk for page, chunk in unique_pages.items() if page != conclusion_page]
            return (leading[: max(limit - 1, 1)] + ([conclusion] if conclusion else []))[:limit]
    ranked: list[tuple[int, EvidenceChunk]] = []
    for chunk in chunks:
        if chunk.page_number < first_special_page:
            continue
        text = _normalise(chunk.text)
        convention_count = len(re.findall(r"\b(convention|conventions|contrat|contrats|operation|operations)\b", text))
        if convention_count == 0:
            continue
        score = min(convention_count, 6)
        if "autres conventions" in text or "autres conventions ou operations" in text:
            score += 30
        if "societe" in text or "filiale" in text or "partie liee" in text:
            score += 8
        if "conclu" in text or "conclues" in text:
            score += 4
        ranked.append((score, chunk))
    return [chunk for _, chunk in sorted(ranked, key=lambda item: (-item[0], item[1].page_number))[:limit]]
