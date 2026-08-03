"""Conservative extraction before the deterministic validation gate."""

from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal
from pathlib import Path

from myfinance_contracts import FinancialFact, SourceReference

from myfinance_agent_docs.catalog import PROJECT_ROOT, load_common_extraction_profile
from myfinance_agent_docs.ingestion import ingest_report

_AMOUNT = re.compile(r"(?<![\d.,-])-?(?:\d{1,3}(?:[ \t\u00a0]\d{3})+|\d{4,})(?![\d.,])")

# These are statement sections, not bank-specific extraction rules.  The accepted
# labels live in data/reference/financial_metrics.json so that business wording is
# versioned independently from the extraction code.
_METRIC_SECTIONS = {
    "total_assets": "balance_sheet",
    "total_liabilities": "balance_sheet",
    "total_equity": "balance_sheet",
    "customer_loans_net": "balance_sheet",
    "customer_deposits": "balance_sheet",
    "net_income": "income_statement",
    "net_banking_income": "income_statement",
}

AUTO_VALIDATED_FACTS_ROOT = PROJECT_ROOT / "data" / "normalized" / "facts" / "auto_validated"


def auto_validated_fact(bank_id: str, year: int, metric_id: str) -> FinancialFact | None:
    """Return a user-safe fact only after deterministic validation has passed."""
    path = AUTO_VALIDATED_FACTS_ROOT / bank_id / str(year) / "financial_facts.json"
    if not path.exists():
        return None
    facts = json.loads(path.read_text(encoding="utf-8"))
    for payload in facts:
        if payload["metric_id"] == metric_id and payload["validation_status"] == "auto_validated":
            return FinancialFact.model_validate(payload)
    return None


def _unit_from_text(text: str) -> tuple[str, str] | None:
    lower = text.lower()
    if "millier de dinars" in lower or "milliers de dinars" in lower or "milliers de dinars tunisiens" in lower:
        return "TND", "thousand"
    if "millions de dinars" in lower or "millions de dinars tunisiens" in lower:
        return "TND", "million"
    if re.search(r"\bk\s*\.\s*tnd\b", lower):
        return "TND", "thousand"
    if re.search(r"\bm\s*\.\s*tnd\b", lower):
        return "TND", "million"
    return None


def _amount(raw: str) -> Decimal:
    return Decimal(re.sub(r"\s+", "", raw))


def _compact(value: str) -> str:
    """Normalise accents, ligatures and PDF character spacing for label matching."""
    repaired = value.replace("\u019f", "ti").replace("’", "'")
    decomposed = unicodedata.normalize("NFKD", repaired)
    return "".join(character for character in decomposed.lower() if character.isalnum())


def _statement_labels() -> dict[str, tuple[str, ...]]:
    profile = load_common_extraction_profile()
    aliases = profile["statement_label_aliases"]
    return {
        metric_id: tuple(_compact(str(label)) for label in labels)
        for metric_id, labels in aliases.items()
    }


def _first_statement_amount(line: str) -> tuple[Decimal, int, int] | None:
    """Return the first financial amount, skipping accounting note identifiers."""
    match = _AMOUNT.search(line)
    if match is None:
        return None
    return _amount(match.group()), match.start(), match.end()


def _document_scope(chunks: list) -> str | None:
    """Resolve the scope for the catalogued individual-report collection.

    The source catalogue contains only individual financial statements.  An
    explicit consolidated marker always wins; conflicting markers are rejected.
    This lets older publications that omit the word ``individuels`` remain
    processable without silently accepting a consolidated report.
    """
    # The declaration is in the first pages. Restricting the search prevents an
    # audit note later in the report from making an individual report ambiguous.
    document_text = _compact("\n".join(chunk.text for chunk in chunks if chunk.page_number <= 3))
    individual = "etatsfinanciersindividuels" in document_text
    consolidated = "etatsfinanciersconsolides" in document_text
    if individual and consolidated:
        return None
    if consolidated:
        return "consolidated"
    return "individual"


def _belongs_to_primary_statement(chunk, required_section: str) -> bool:
    """Allow an unclassified opening statement page, never another statement."""
    return chunk.section == required_section or (
        chunk.section == "unclassified" and chunk.page_number <= 5
    )


def extract_candidate_facts(report: SourceReference) -> list[FinancialFact]:
    """Extract only unambiguous first-column amounts from the primary statements.

    The ``candidate`` status is transient and in-memory only: the caller must pass
    the result to :mod:`myfinance_agent_docs.validation`.  The chat never reads
    these values directly.
    """
    ingested = ingest_report(report)
    facts: list[FinancialFact] = []
    seen_metrics: set[str] = set()
    scope = _document_scope(ingested.chunks)
    page_units = {
        chunk.page_number: unit
        for chunk in ingested.chunks
        if (unit := _unit_from_text(chunk.text)) is not None
    }
    statement_labels = _statement_labels()
    for chunk in ingested.chunks:
        # The unit is normally printed once in a page heading and can therefore
        # belong to a preceding chunk of the same source page.
        unit = _unit_from_text(chunk.text) or page_units.get(chunk.page_number)
        if unit is None:
            continue
        for metric_id, accepted_labels in statement_labels.items():
            required_section = _METRIC_SECTIONS[metric_id]
            if metric_id in seen_metrics or not _belongs_to_primary_statement(chunk, required_section):
                continue
            for line in chunk.text.splitlines():
                compact_line = _compact(line)
                if not any(label in compact_line for label in accepted_labels):
                    continue
                parsed_amount = _first_statement_amount(line)
                if parsed_amount is None:
                    continue
                value, amount_start, _ = parsed_amount
                facts.append(
                    FinancialFact(
                        fact_id=f"{chunk.document_id}:{metric_id}",
                        metric_id=metric_id,
                        raw_label=line[:amount_start].strip(),
                        value=value,
                        currency=unit[0],
                        unit_scale=unit[1],  # type: ignore[arg-type]
                        reporting_year=report.year,
                        scope=scope,
                        document_id=chunk.document_id,
                        source_path=chunk.source_path,
                        source_sha256=chunk.source_sha256,
                        page_number=chunk.page_number,
                        # When a PDF has no detectable heading, the accepted
                        # metric itself identifies the primary statement.  The
                        # original page and line remain the proof.
                        section=required_section if chunk.section == "unclassified" else chunk.section,
                        source_excerpt=line.strip(),
                    )
                )
                seen_metrics.add(metric_id)
                break
    return facts


def write_candidate_facts(output_path: Path, report: SourceReference) -> list[FinancialFact]:
    """Legacy migration helper; new pipelines keep extraction in memory."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    facts = extract_candidate_facts(report)
    temporary = output_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps([fact.model_dump(mode="json") for fact in facts], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return facts


def promote_reviewed_candidates(
    candidate_path: Path, output_path: Path, *, scope: str
) -> list[FinancialFact]:
    """Legacy helper retained for migration; new pipelines use validation.py instead."""
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidates = [FinancialFact.model_validate(item) for item in payload]
    if not candidates:
        raise ValueError("No candidate facts are available for review.")
    if any(fact.validation_status != "candidate" for fact in candidates):
        raise ValueError("Only candidate facts can be promoted to verified facts.")
    if scope not in {"individual", "consolidated"}:
        raise ValueError("A verified fact requires an explicit accounting scope.")

    verified = [
        fact.model_copy(update={"validation_status": "verified", "scope": scope})
        for fact in candidates
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps([fact.model_dump(mode="json") for fact in verified], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return verified
