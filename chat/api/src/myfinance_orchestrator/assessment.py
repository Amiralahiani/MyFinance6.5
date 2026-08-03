"""Deterministic request assessment before any model is allowed to answer."""

from __future__ import annotations

import re
import unicodedata

from myfinance_agent_docs.catalog import assessment_metrics, bank_definitions, reports_for
from myfinance_contracts import RequestAssessment


def _normalise(value: str) -> str:
    normalised = "".join(
        character
        for character in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(character) != "Mn"
    )
    return normalised.replace("’", "'").replace("‘", "'").replace("‐", "-")


def _find_banks(message: str) -> list[str]:
    normalised = _normalise(message)
    found: list[str] = []
    for bank_id, (_, aliases) in bank_definitions().items():
        if any(re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalised) for alias in aliases):
            found.append(bank_id)
    return found


def _find_years(message: str) -> list[int]:
    return sorted({int(value) for value in re.findall(r"\b20\d{2}\b", message)})


def _find_metric(message: str) -> str | None:
    normalised = _normalise(message)
    for metric, aliases in assessment_metrics().items():
        if any(_normalise(alias) in normalised for alias in aliases):
            return metric
    return None


def _clarification_reason(missing: list[str]) -> str:
    """Explain the one missing element in language suitable for the user."""
    if missing == ["annee ou periode"]:
        return (
            "Pour vous répondre avec précision, indiquez l’année concernée "
            "(par exemple : « Quel est le PNB de BIAT en 2025 ? »)."
        )
    if missing == ["banque a analyser"]:
        return "Pour vous répondre avec rigueur, indiquez la banque à analyser afin que je vérifie le bon rapport officiel."
    if missing == ["indicateur financier a analyser"]:
        return "Pour vous répondre avec rigueur, indiquez l’indicateur financier à analyser (par exemple PNB, résultat net ou dépôts)."
    return "Pour préparer une analyse fiable, j’ai besoin de la banque, de l’année et de l’indicateur financier à analyser."


def assess_request(message: str) -> RequestAssessment:
    """Return answer/clarify/abstain without guessing financial facts."""
    if not message.strip():
        return RequestAssessment(
            decision="clarify",
            reason="La demande est vide.",
            missing_information=["banque", "periode", "indicateur financier"],
        )

    banks = _find_banks(message)
    years = _find_years(message)
    metric = _find_metric(message)
    missing: list[str] = []
    if not banks:
        missing.append("banque a analyser")
    if not years:
        missing.append("annee ou periode")
    if metric is None:
        missing.append("indicateur financier a analyser")
    if missing:
        return RequestAssessment(
            decision="clarify",
            reason=_clarification_reason(missing),
            missing_information=missing,
            detected_banks=banks,
            detected_years=years,
            detected_metric=metric,
        )

    available_reports = reports_for(banks, years)
    expected_reports = len(banks) * len(years)
    if len(available_reports) != expected_reports:
        return RequestAssessment(
            decision="abstain",
            reason=(
                "Les rapports officiels requis ne sont pas tous disponibles pour les banques "
                "et annees demandees."
            ),
            sources=available_reports,
            detected_banks=banks,
            detected_years=years,
            detected_metric=metric,
        )

    return RequestAssessment(
        decision="answer",
        reason=(
            "La banque, la periode et l'indicateur sont identifies; les rapports officiels "
            "requis sont disponibles pour extraction et verification."
        ),
        sources=available_reports,
        detected_banks=banks,
        detected_years=years,
        detected_metric=metric,
    )
