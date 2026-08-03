"""Structured reading index for the source-preserving report corpus."""

from __future__ import annotations

import json
import re
from pathlib import Path

from myfinance_contracts import EvidenceChunk

from myfinance_agent_docs.catalog import PROJECT_ROOT

CORPUS_ROOT = PROJECT_ROOT / "data" / "normalized" / "corpus"
INDEX_ROOT = PROJECT_ROOT / "data" / "normalized" / "section-index"


def _normalise(value: str) -> str:
    return " ".join(value.lower().replace("é", "e").replace("è", "e").replace("ê", "e").replace("à", "a").replace("ù", "u").replace("’", "'").split())


def _chunks(bank_id: str, year: int) -> list[EvidenceChunk]:
    path = CORPUS_ROOT / bank_id / str(year) / "evidence_chunks.jsonl"
    if not path.exists():
        return []
    return [EvidenceChunk.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]


def build_section_index(bank_id: str, year: int) -> dict:
    """Classify report regions needed for documentary query planning."""
    chunks = _chunks(bank_id, year)
    special_start = next((chunk.page_number for chunk in chunks if "rapport special des commissaires" in _normalise(chunk.text)), None)
    notes: list[dict] = []
    for chunk in chunks:
        match = re.search(r"(?im)^\s*note\s+([ivxlcdm0-9]+)\s*[–-]\s*([^\n]+)", chunk.text)
        if match:
            notes.append({"page_number": chunk.page_number, "note": match.group(1), "title": match.group(2).strip()})
    related_party_notes = [
        note for note in notes if "parties liees" in _normalise(note["title"])
    ]
    convention_pages: list[int] = []
    conclusion_page: int | None = None
    if special_start is not None:
        for chunk in chunks:
            if chunk.page_number < special_start:
                continue
            text = _normalise(chunk.text)
            if re.search(r"\b(convention|conventions|contrat|contrats|operation|operations)\b", text):
                convention_pages.append(chunk.page_number)
            if "n'ont pas revele" in text and "autres conventions" in text:
                conclusion_page = chunk.page_number
    return {
        "bank_id": bank_id,
        "reporting_year": year,
        "special_audit_report": {"start_page": special_start, "conclusion_page": conclusion_page},
        "notes": notes,
        "related_party_notes": related_party_notes,
        "convention_pages": sorted(set(convention_pages)),
    }


def write_section_index(bank_id: str, year: int) -> Path:
    index = build_section_index(bank_id, year)
    path = INDEX_ROOT / bank_id / f"{year}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_section_index(bank_id: str, year: int) -> dict:
    path = INDEX_ROOT / bank_id / f"{year}.json"
    if not path.exists():
        return build_section_index(bank_id, year)
    return json.loads(path.read_text(encoding="utf-8"))
