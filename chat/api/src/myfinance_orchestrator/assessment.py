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
            "To answer precisely, please provide the relevant year "
            "(for example: “What was BIAT's net banking income in 2025?”)."
        )
    if missing == ["banque a analyser"]:
        return "To answer reliably, please specify the bank so that I can check the correct official report."
    if missing == ["indicateur financier a analyser"]:
        return "To answer reliably, please specify the financial metric to analyse (for example, net banking income, net income or deposits)."
    return "To prepare a reliable analysis, I need the bank, year and financial metric to analyse."


def assess_request(message: str) -> RequestAssessment:
    """Return answer/clarify/abstain without guessing financial facts."""
    if not message.strip():
        return RequestAssessment(
            decision="clarify",
            reason="The request is empty.",
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
                "The required official reports are not all available for the requested banks "
                "and years."
            ),
            sources=available_reports,
            detected_banks=banks,
            detected_years=years,
            detected_metric=metric,
        )

    return RequestAssessment(
        decision="answer",
        reason=(
            "The bank, period and metric have been identified; the required official reports "
            "are available for extraction and verification."
        ),
        sources=available_reports,
        detected_banks=banks,
        detected_years=years,
        detected_metric=metric,
    )
