"""Curated official references that may ground a general-education answer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
GENERAL_SOURCES_PATH = PROJECT_ROOT / "data" / "reference" / "general_sources.json"


def sources_for_general_question(message: str, topic: str | None = None) -> list[dict[str, str]]:
    """Return only pre-approved official sources relevant to a question."""
    sources = _load_sources()
    current_matches = _matching_sources(sources, message)
    if current_matches:
        return current_matches
    return _matching_sources(sources, f"{message} {topic or ''}")


def _load_sources() -> list[dict[str, Any]]:
    try:
        payload = json.loads(GENERAL_SOURCES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []
    items = payload.get("sources") if isinstance(payload, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _matching_sources(sources: list[dict[str, Any]], text: str) -> list[dict[str, str]]:
    query = text.casefold()
    matches: list[dict[str, str]] = []
    for item in sources:
        terms = item.get("match_terms")
        if not isinstance(terms, list) or not any(str(term).casefold() in query for term in terms):
            continue
        source = {
            key: str(item[key])
            for key in ("source_id", "title", "url", "supported_context")
            if item.get(key)
        }
        if {"source_id", "title", "url", "supported_context"} <= source.keys():
            matches.append(source)
    return matches
