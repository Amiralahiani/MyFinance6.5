"""Whole-request normalisation before the financial-document router."""

from __future__ import annotations

import os
import re
import unicodedata

from myfinance_agent_docs.catalog import bank_definitions, documentary_glossary

from myfinance_orchestrator.model_provider import json_object

DOCUMENT_TERMS = {
    "portefeuille", "encaissement", "provision", "provisions", "créance", "créances",
    "risque", "risques", "crédit", "crédits", "contrepartie", "engagement", "engagements",
    "bilan", "trésorerie", "liquidité", "fonds", "propres", "clientèle",
    "transaction", "transactions", "partie", "parties", "liée", "liées", "convention", "conventions",
}
NON_CORRECTABLE = {
    "quel", "quelle", "quels", "quelles", "est", "sont", "dans", "avec", "pour", "sur",
    "quoi", "comment", "pourquoi", "de", "du", "des", "la", "le", "les", "en", "et",
}


def _normalise(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(character) != "Mn"
    ).replace("’", "'")


def _distance(left: str, right: str) -> int:
    """Small dependency-free Levenshtein distance for a short financial lexicon."""
    previous = list(range(len(right) + 1))
    for index, left_char in enumerate(left, start=1):
        current = [index]
        for other_index, right_char in enumerate(right, start=1):
            current.append(min(current[-1] + 1, previous[other_index] + 1, previous[other_index - 1] + (left_char != right_char)))
        previous = current
    return previous[-1]


def _financial_lexicon() -> dict[str, str]:
    """Build a domain-only correction list.

    A metric alias can contain ordinary French words (for example “auprès”).
    Those words must never be treated as spelling candidates: correcting normal
    prose is worse than leaving a harmless typo for the document retriever.
    """
    values = set(DOCUMENT_TERMS)
    for _, aliases in bank_definitions().values():
        values.update(aliases)
    for concept in documentary_glossary():
        aliases = concept.get("aliases", [])
        if isinstance(aliases, dict):
            for aliases_by_language in aliases.values():
                values.update(str(alias) for alias in aliases_by_language)
        else:
            values.update(str(alias) for alias in aliases)

    lexicon: dict[str, str] = {}
    for value in values:
        for token in re.findall(r"[A-Za-zÀ-ÿ]{4,}", value):
            lexicon.setdefault(_normalise(token), token.lower())
    return lexicon


FINANCIAL_LEXICON = _financial_lexicon()


def correct_financial_spelling(message: str) -> tuple[str, list[dict[str, str]]]:
    """Correct only one unambiguous, close financial-word match at a time."""
    corrections: list[dict[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        original = match.group(0)
        word = _normalise(original)
        if len(word) < 5 or word in FINANCIAL_LEXICON or word in NON_CORRECTABLE:
            return original
        # A single edit catches ordinary keyboard omissions such as
        # "potfeuille" while avoiding semantic substitutions such as
        # "parties" -> "pertes". Multi-edit suggestions require user confirmation.
        maximum = 2
        candidates = [
            (candidate, _distance(word, candidate))
            for candidate in FINANCIAL_LEXICON
            if candidate[0] == word[0] and abs(len(candidate) - len(word)) <= maximum
        ]
        candidates = [(candidate, distance) for candidate, distance in candidates if distance <= maximum]
        if not candidates:
            return original
        best_distance = min(distance for _, distance in candidates)
        best = [candidate for candidate, distance in candidates if distance == best_distance]
        if len(best) != 1:
            return original
        # Two edits are accepted only for the curated financial-document terms,
        # never for ordinary prose or a metric alias that could mean something
        # different in a sentence.
        if best_distance == 2 and best[0] not in {_normalise(term) for term in DOCUMENT_TERMS}:
            return original
        corrected = FINANCIAL_LEXICON[best[0]]
        corrections.append({"from": original, "to": corrected})
        return corrected

    corrected_message = re.sub(r"[A-Za-zÀ-ÿ]{4,}", replace, message)
    return corrected_message, corrections


def _repair_question_structure(message: str) -> str:
    """Fix unambiguous sentence structure, including glued bank names.

    This is deliberately not a generic autocorrect.  It only repairs patterns
    whose meaning is stable in a request, then leaves semantic interpretation to
    the router or the optional full-sentence rewrite model.
    """
    repaired = " ".join(message.strip().replace("’", "'").split())
    repaired = re.sub(r"\bwhat'?s\b", "what is", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bwhats\b", "what is", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bc\s*(?:'|e)?st\b", "c'est", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bc\s+quoi\b", "c'est quoi", repaired, flags=re.IGNORECASE)
    for _, aliases in bank_definitions().values():
        for alias in aliases:
            # `what isbiat`, `c'estBIAT` and similar omissions are one request,
            # not two independent spelling errors.
            repaired = re.sub(
                rf"(?i)\b(what\s+is|who\s+is|c'?est\s+quoi|c'?est)\s*({re.escape(alias)})\b",
                lambda match: f"{match.group(1)} {match.group(2)}",
                repaired,
            )
            repaired = re.sub(
                rf"(?i)\b(?:whats?|whatis)({re.escape(alias)})\b",
                lambda match: f"what is {match.group(1)}",
                repaired,
            )
            repaired = re.sub(
                rf"(?i)\bcest({re.escape(alias)})\b",
                lambda match: f"c'est {match.group(1)}",
                repaired,
            )
    return repaired


def _model_rewrite_enabled() -> bool:
    # A rewrite is not a safe source of meaning: even a fluent model can turn
    # “all banks” into “a bank”.  The turn planner always sees the raw user
    # message, and full-sentence rewrites stay an explicit opt-in experiment.
    return os.environ.get("MYFINANCE_QUERY_REWRITE", "0").strip().lower() in {"1", "true", "yes"}


def _rewrite_full_sentence(message: str) -> str | None:
    """Optionally ask the configured model to repair the request, never answer it."""
    if not _model_rewrite_enabled():
        return None
    payload = json_object(
        """Normalize this user's request for a financial-report search.
Correct spelling, grammar, conjugation and missing spaces while preserving its exact intent.
Keep every bank name, number, year and financial topic unchanged. Do not answer the request,
do not add any fact, and return JSON only in this shape: {\"message\": \"...\"}.

User request:
""" + message,
        max_tokens=100,
    )
    candidate = payload.get("message") if payload else None
    if not isinstance(candidate, str):
        return None
    candidate = " ".join(candidate.strip().split())
    if not candidate or len(candidate) > 600:
        return None
    # A rewrite may improve language, but it must not silently remove dates or
    # bank names that make source selection deterministic.
    original_years = set(re.findall(r"\b20\d{2}\b", message))
    if not original_years.issubset(set(re.findall(r"\b20\d{2}\b", candidate))):
        return None
    for _, aliases in bank_definitions().values():
        if any(_normalise(alias) in _normalise(message) for alias in aliases) and not any(
            _normalise(alias) in _normalise(candidate) for alias in aliases
        ):
            return None
    return candidate


def normalise_financial_request(message: str) -> tuple[str, list[dict[str, str]]]:
    """Understand a malformed request as a whole before the source-only workflow.

    The optional model only rewrites the query.  It receives no report content
    and cannot produce a user-facing financial answer; source retrieval remains
    mandatory after this step.
    """
    structured = _repair_question_structure(message)
    corrected, _ = correct_financial_spelling(structured)
    rewritten = _rewrite_full_sentence(corrected)
    final = rewritten or corrected
    return final, ([{"from": message, "to": final}] if final != message else [])
