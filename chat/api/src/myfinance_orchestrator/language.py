"""High-confidence spelling repair for financial questions before assessment."""

from __future__ import annotations

import re
import unicodedata

from myfinance_agent_docs.catalog import bank_definitions

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
        maximum = 1
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
        corrected = FINANCIAL_LEXICON[best[0]]
        corrections.append({"from": original, "to": corrected})
        return corrected

    corrected_message = re.sub(r"[A-Za-zÀ-ÿ]{4,}", replace, message)
    return corrected_message, corrections
