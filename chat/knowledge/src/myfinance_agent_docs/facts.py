"""Conservative extraction before the deterministic validation gate."""

from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from myfinance_contracts import FinancialFact, SourceReference

from myfinance_agent_docs.catalog import (
    PROJECT_ROOT,
    load_common_extraction_profile,
    load_metric_catalog,
    reports_for,
)
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


@lru_cache(maxsize=512)
def source_matched_fact(bank_id: str, year: int, metric_id: str) -> FinancialFact | None:
    """Extract one exact statement line when it is outside the validation core.

    This is intentionally separate from ``auto_validated_fact``: it returns a
    value only when one accepted catalogue label occurs once on the designated
    primary statement page.  The caller must present it as source-extracted,
    never as automatically validated.
    """
    definition = next(
        (item for item in load_metric_catalog() if item.get("metric_id") == metric_id),
        None,
    )
    reports = reports_for([bank_id], [year])
    if definition is None or len(reports) != 1:
        return None
    source_profile = _source_profile_for_bank(definition, bank_id, year)
    source_section = source_profile.get("source_section")
    source_note_family = source_profile.get("source_note_family")
    labels = [_compact(str(value)) for value in source_profile.get("accepted_statement_labels", [])]
    if not isinstance(source_section, str) or not labels:
        return None
    catalog_unit_payload = definition.get("unit")
    catalog_unit = (
        (str(catalog_unit_payload["currency"]), str(catalog_unit_payload["unit_scale"]))
        if isinstance(catalog_unit_payload, dict)
        and isinstance(catalog_unit_payload.get("currency"), str)
        and isinstance(catalog_unit_payload.get("unit_scale"), str)
        else None
    )

    report = reports[0]
    ingested = ingest_report(report)
    scope = _document_scope(ingested.chunks)
    if scope != "individual":
        return None
    page_units = {
        chunk.page_number: unit
        for chunk in ingested.chunks
        if (unit := _unit_from_text(chunk.text)) is not None
    }
    matches: list[FinancialFact] = []
    # Some reports print a note heading at the bottom of one page and its
    # first quantified table row at the top of the next.  Carry that declared
    # note for one immediately following page only; this preserves the strict
    # note/label proof and never opens a broad cross-document label search.
    note_continues_from_previous_page = False
    previous_page_number: int | None = None
    for chunk in ingested.chunks:
        unit = _unit_from_text(chunk.text) or page_units.get(chunk.page_number)
        direct_note_lines = _declared_note_line_indices(chunk.text, source_note_family, labels) if source_section == "notes" else set()
        if (
            source_section == "notes"
            and note_continues_from_previous_page
            and previous_page_number is not None
            and chunk.page_number == previous_page_number + 1
        ):
            direct_note_lines |= _first_labelled_note_row_indices(chunk.text, labels)
        requires_declared_note = source_section == "notes" and source_note_family is not None
        if (requires_declared_note and not direct_note_lines) or (
            not requires_declared_note and not _belongs_to_primary_statement(chunk, source_section) and not direct_note_lines
        ):
            note_continues_from_previous_page = (
                source_section == "notes"
                and _declares_note(chunk.text, source_note_family)
                and not direct_note_lines
            )
            previous_page_number = chunk.page_number
            continue
        for line_index, line in enumerate(chunk.text.splitlines()):
            compact_line = _compact(line)
            if not any(label in compact_line for label in labels):
                continue
            # Notes often continue on a page the PDF extractor leaves
            # unclassified.  The note family plus its first two-column labelled
            # row form a stricter proof than a broad section guess.
            if requires_declared_note and line_index not in direct_note_lines:
                continue
            if not requires_declared_note and not _belongs_to_primary_statement(chunk, source_section) and line_index not in direct_note_lines:
                continue
            resolved_unit = unit or (catalog_unit if line_index in direct_note_lines else None)
            if resolved_unit is None:
                continue
            parsed_amount = _first_statement_amount(line)
            if parsed_amount is None:
                continue
            value, amount_start, _ = parsed_amount
            matches.append(
                FinancialFact(
                    fact_id=f"{chunk.document_id}:{metric_id}",
                    metric_id=metric_id,
                    raw_label=line[:amount_start].strip(),
                    value=value,
                    currency=resolved_unit[0],
                    unit_scale=resolved_unit[1],  # type: ignore[arg-type]
                    reporting_year=year,
                    scope=scope,
                    document_id=chunk.document_id,
                    source_path=chunk.source_path,
                    source_sha256=chunk.source_sha256,
                    page_number=chunk.page_number,
                    section=source_section,
                    source_excerpt=line.strip(),
                )
            )
        note_continues_from_previous_page = (
            source_section == "notes"
            and _declares_note(chunk.text, source_note_family)
            and not direct_note_lines
        )
        previous_page_number = chunk.page_number
    return matches[0] if len(matches) == 1 else None


def _source_profile_for_bank(definition: dict, bank_id: str, year: int | None = None) -> dict:
    """Resolve a bank/year source layout without broadening another report's labels."""
    profile = {
        "source_section": definition.get("source_section"),
        "source_note_family": definition.get("source_note_family"),
        "accepted_statement_labels": definition.get("accepted_statement_labels", []),
    }
    bank_profiles = definition.get("bank_source_profiles")
    if isinstance(bank_profiles, dict):
        override = bank_profiles.get(bank_id)
        if isinstance(override, dict):
            profile.update({key: value for key, value in override.items() if key in profile})
    year_profiles = definition.get("bank_year_source_profiles")
    if isinstance(year_profiles, dict) and year is not None:
        override = year_profiles.get(f"{bank_id}:{year}")
        if isinstance(override, dict):
            profile.update({key: value for key, value in override.items() if key in profile})
    return profile


def _declared_note_line_indices(text: str, note_family: object, labels: list[str]) -> set[int]:
    """Find the first direct quantified row below a declared financial note.

    A note's primary row can contain two annual columns or additional variance
    columns.  Later maturity tables repeat the label but occur after that row.
    """
    note_families = (
        [note_family]
        if isinstance(note_family, str) and note_family.strip()
        else [item for item in note_family if isinstance(item, str) and item.strip()]
        if isinstance(note_family, list)
        else []
    )
    if not note_families:
        return set()
    lines = text.splitlines()
    note_index = next((index for index, line in enumerate(lines) if any(_note_family_matches_line(family, line) for family in note_families)), None)
    if note_index is None:
        return set()
    return _first_labelled_note_row_indices("\n".join(lines[note_index + 1 :]), labels, offset=note_index + 1)


def _declares_note(text: str, note_family: object) -> bool:
    note_families = (
        [note_family]
        if isinstance(note_family, str) and note_family.strip()
        else [item for item in note_family if isinstance(item, str) and item.strip()]
        if isinstance(note_family, list)
        else []
    )
    return any(_note_family_matches_line(family, line) for family in note_families for line in text.splitlines())


def _note_family_matches_line(family: str, line: str) -> bool:
    """Match a structured note identifier without mistaking figures for it."""
    parts = re.findall(r"[A-Za-z]+|\d+", family)
    if not parts:
        return False
    expression = r"[^A-Za-z0-9]*".join(re.escape(part) for part in parts)
    return re.search(rf"(?<![A-Za-z0-9]){expression}(?![A-Za-z0-9])", line, flags=re.IGNORECASE) is not None


def _first_labelled_note_row_indices(text: str, labels: list[str], *, offset: int = 0) -> set[int]:
    """Return the first labelled two-column row from a declared note body."""
    for index, line in enumerate(text.splitlines(), start=offset):
        compact_line = _compact(line)
        if not any(compact_line.startswith(label) for label in labels):
            continue
        if len(_AMOUNT.findall(line)) >= 2:
            return {index}
    return set()


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


def _statement_profiles(bank_id: str, year: int) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Resolve the primary-statement section and labels for one exact report."""
    profile = load_common_extraction_profile()
    aliases = profile["statement_label_aliases"]
    definitions = {str(item["metric_id"]): item for item in load_metric_catalog()}
    resolved: dict[str, tuple[str, tuple[str, ...]]] = {}
    for metric_id, labels in aliases.items():
        definition = definitions.get(metric_id)
        source_profile = _source_profile_for_bank(definition, bank_id, year) if definition else {}
        section = str(source_profile.get("source_section") or _METRIC_SECTIONS[metric_id])
        # Keep the common aliases as the compatibility baseline. A report-level
        # source profile can add a clean exceptional label, but must never make
        # another core statement line disappear from candidate extraction.
        source_labels = [*labels, *(source_profile.get("accepted_statement_labels") or [])]
        resolved[metric_id] = (section, tuple(dict.fromkeys(_compact(str(label)) for label in source_labels)))
    return resolved


def _first_statement_amount(line: str) -> tuple[Decimal, int, int] | None:
    """Return the first financial amount, skipping accounting note identifiers."""
    # A few PDFs encode the thousands separator as a private-use glyph.  Keep
    # character positions stable so the source label still points to the
    # original excerpt, while treating only an inter-digit glyph as a space.
    # This does not loosen matching for labels or note identifiers.
    normalized_line = re.sub(r"(?<=\d)[^\d\s.,-](?=\d)", " ", line)
    match = _AMOUNT.search(normalized_line)
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
    statement_profiles = _statement_profiles(report.bank_id, report.year)
    for chunk in ingested.chunks:
        # The unit is normally printed once in a page heading and can therefore
        # belong to a preceding chunk of the same source page.
        unit = _unit_from_text(chunk.text) or page_units.get(chunk.page_number)
        if unit is None:
            continue
        for metric_id, (required_section, accepted_labels) in statement_profiles.items():
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
