"""Reproducible extraction of source-preserving PDF evidence chunks.

This module deliberately does not infer financial values. It produces auditable
document and page/chunk records; value extraction will consume these records later.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from myfinance_contracts import DocumentRecord, EvidenceChunk, SourceReference
from pypdf import PdfReader

from myfinance_agent_docs.catalog import PROJECT_ROOT, load_catalog


@dataclass(frozen=True)
class IngestedReport:
    document: DocumentRecord
    chunks: list[EvidenceChunk]


def _normalise(text: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(character) != "Mn"
    )


def classify_section(page_text: str) -> str:
    """Classify a page conservatively from its visible financial-statement heading."""
    heading = _normalise(page_text[:700])
    if "etat des engagements hors bilan" in heading:
        return "off_balance_sheet"
    if "etat de resultat" in heading or "compte de resultat" in heading:
        return "income_statement"
    if "flux de tresorerie" in heading:
        return "cash_flow_statement"
    if "variation des capitaux propres" in heading:
        return "equity_statement"
    if re.search(r"\bbilan\b", heading):
        return "balance_sheet"
    if "notes aux etats financiers" in heading or re.search(r"\bnotes\b", heading):
        return "notes"
    return "unclassified"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean_text(text: str) -> str:
    """Keep table columns while normalising whitespace introduced by PDF extraction."""
    def repair_mojibake(line: str) -> str:
        """Repair a UTF-8 sequence incorrectly decoded by a PDF text layer when safe."""
        if "Ã" not in line:
            return line
        try:
            return line.encode("latin-1").decode("utf-8")
        except UnicodeError:
            return line

    # One space remains part of a formatted number (e.g. ``22 944 526``).
    # Two spaces represent a visual column boundary after pypdf's layout extraction.
    lines = [
        re.sub(r"[ \t]{3,}", "  ", repair_mojibake(line)).strip()
        for line in text.splitlines()
    ]
    return "\n".join(line for line in lines if line)


def _split_text(text: str, maximum_characters: int = 1_800, overlap: int = 220) -> list[str]:
    """Split a page without losing context; no chunk crosses a source page boundary."""
    if len(text) <= maximum_characters:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + maximum_characters, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start, end)
            if boundary > start + maximum_characters // 2:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def ingest_report(report: SourceReference) -> IngestedReport:
    """Extract page-level evidence from one local report with stable IDs and provenance."""
    source_path = PROJECT_ROOT / report.path
    source_hash = _sha256(source_path)
    document_id = f"{report.bank_id}-{report.year}-{source_hash[:16]}"
    reader = PdfReader(source_path)
    document = DocumentRecord(
        document_id=document_id,
        bank_id=report.bank_id,
        bank_name=report.bank_name,
        reporting_year=report.year,
        source_path=report.path,
        sha256=source_hash,
        page_count=len(reader.pages),
    )

    chunks: list[EvidenceChunk] = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = _clean_text(page.extract_text(extraction_mode="layout") or "")
        section = classify_section(page_text)
        for chunk_number, chunk_text in enumerate(_split_text(page_text), start=1):
            chunks.append(
                EvidenceChunk(
                    chunk_id=f"{document_id}-p{page_number}-c{chunk_number}",
                    document_id=document_id,
                    bank_id=report.bank_id,
                    bank_name=report.bank_name,
                    reporting_year=report.year,
                    page_number=page_number,
                    section=section,
                    source_path=report.path,
                    source_sha256=source_hash,
                    text=chunk_text,
                )
            )
    return IngestedReport(document=document, chunks=chunks)


def write_corpus(output_dir: Path, reports: list[SourceReference] | None = None) -> tuple[int, int]:
    """Atomically write the source-preserving JSONL chunks for known reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_reports = reports if reports is not None else load_catalog()
    documents: list[DocumentRecord] = []
    chunk_count = 0
    chunks_tmp = output_dir / "evidence_chunks.jsonl.tmp"
    documents_tmp = output_dir / "documents.json.tmp"
    with chunks_tmp.open("w", encoding="utf-8") as destination:
        for report in selected_reports:
            ingested = ingest_report(report)
            documents.append(ingested.document)
            for chunk in ingested.chunks:
                destination.write(json.dumps(chunk.model_dump(), ensure_ascii=False) + "\n")
                chunk_count += 1

    documents_tmp.write_text(
        json.dumps([document.model_dump() for document in documents], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    chunks_tmp.replace(output_dir / "evidence_chunks.jsonl")
    documents_tmp.replace(output_dir / "documents.json")
    return len(documents), chunk_count
