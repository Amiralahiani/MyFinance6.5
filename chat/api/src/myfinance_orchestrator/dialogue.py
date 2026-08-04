"""Conversation-first routing for automatically validated metrics and documentary analysis."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from myfinance_agent_docs.catalog import bank_definitions, reports_for
from myfinance_agent_docs.corpus import (
    retrieve_entity_evidence,
    retrieve_evidence,
    retrieve_related_conventions,
)
from myfinance_agent_docs.facts import auto_validated_fact
from myfinance_contracts import ConversationContext, ReportedValueAnswer

from myfinance_orchestrator.assessment import assess_request
from myfinance_orchestrator.ollama import answer_from_evidence

DOCUMENTARY_INTENT = re.compile(r"\b(pourquoi|comment|explique|analyse|que dit|qu'est ce|c'est quoi|que signifie|risque|provision|portefeuille|encaissement|transactions?|parties? liees?|conventions?|why|how|explain|analysis|what does|what is|what are|risk|provision|portfolio|collection|related parties?)\b")
EXPANSION_FOLLOW_UP = re.compile(r"\b(autres?|d'autre|y a[- ]t[- ]il|existe|encore|liste|other|another|any more|more|list)\b")
REFERENCE_FOLLOW_UP = re.compile(r"\b(ce contrat|cette convention|ce point|cela|ca|en pratique|pourquoi|this contract|this agreement|this point|in practice|why)\b")


def _topic(message: str) -> str:
    return re.sub(r"\s+", " ", message).strip(" ?!.")


def _normalise(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(character) != "Mn"
    ).replace("’", "'").replace("-", "-")


def _related_party_scope(message: str) -> bool:
    """Recognise the subject without depending on accents or singular/plural."""
    text = _normalise(message)
    has_operation = bool(re.search(r"\b(transactions?|conventions?)\b", text))
    has_related_party = bool(re.search(r"\bparties?\s+liees?\b", text))
    return has_operation and has_related_party


def _context(bank_id: str | None, year: int | None, *, mode: str, topic: str | None = None, document_scope: str | None = None, document_anchor: str | None = None, document_anchor_page: int | None = None, metric_id: str | None = None) -> ConversationContext:
    name = bank_definitions().get(bank_id, (None, []))[0] if bank_id else None
    return ConversationContext(
        mode=mode,
        bank_id=bank_id,
        bank_name=name,
        reporting_year=year,
        topic=topic,
        document_scope=document_scope,
        document_anchor=document_anchor,
        document_anchor_page=document_anchor_page,
        metric_id=metric_id,
    )


def _document_clarification(context: ConversationContext) -> dict[str, Any]:
    missing: list[str] = []
    if not context.bank_id:
        missing.append("banque a analyser")
    if not context.reporting_year:
        missing.append("annee ou periode")
    return {
        "type": "clarification",
        "mode": "document",
        "context": context.model_dump(),
        "missing_information": missing,
        "message": "To continue this documentary analysis, please provide " + ("the bank and year" if len(missing) == 2 else "the missing detail") + ".",
    }


def _related_conventions_analysis(evidence: list[Any], *, anchor: str | None = None) -> dict[str, Any]:
    """Return an auditable answer structure for a related-party scope expansion.

    The first note and the auditors' special report have different legal roles.  The
    structure makes that distinction visible instead of hiding it in a fluent but
    potentially ambiguous paragraph.
    """
    primary = evidence[0]
    special_report_evidence = evidence[1:]
    special_report_pages = sorted({chunk.page_number for chunk in special_report_evidence})
    completion = next(
        (
            chunk
            for chunk in special_report_evidence
            if "n'ont pas revele" in _normalise(chunk.text)
            and "autres conventions" in _normalise(chunk.text)
        ),
        None,
    )
    citations = " ".join(f"[p. {chunk.page_number}]" for chunk in evidence)
    starting_point = anchor or "the transaction initially reviewed"
    findings = [
        {
            "title": f"Starting point: {starting_point}",
            "text": "The first excerpt is the one retained to establish the initial documentary record.",
            "pages": [primary.page_number],
        },
        {
            "title": "Other agreements presented",
            "text": "The special-report excerpts present the agreements or transactions examined within its legal scope.",
            "pages": special_report_pages,
        },
    ]
    if completion is not None:
        findings.append(
            {
                "title": "Scope of the statement",
                "text": "The special report specifies the scope of its work for the agreements and transactions it examines.",
                "pages": [completion.page_number],
            }
        )
    return {
        "intent": "scope_expansion",
        "scope_label": "Auditors’ special report",
        "scope_explanation": (
            "The initial excerpt describes a related-party transaction; the special report "
            "lists the agreements and transactions examined within the legal framework. The two "
            "scopes overlap, but are not interchangeable."
        ),
        "direct_answer": (
            "Yes. Beyond the initial excerpt, the special report presents other agreements or "
            "transactions examined by the auditors. Each one should not automatically be labelled "
            "as a related-party transaction. "
            f"{citations}"
        ),
        "findings": findings,
    }


def _anchor_candidates(*values: str | None) -> list[str]:
    """Extract explicit entity anchors, never generic bank or report words."""
    ignored = {"BIAT", "PDF", "TND", "BCT", "HTVA"}
    candidates: list[str] = []
    for value in values:
        if not value:
            continue
        for token in re.findall(r"\b[A-Z]{2,}(?:\s+[A-Z]{2,})?\b", value):
            if token not in ignored and token not in candidates:
                candidates.append(token)
    return candidates


def _resolve_document_anchor(updated: ConversationContext, previous: ConversationContext) -> tuple[ConversationContext, list[Any] | None, str | None]:
    """Resolve the entity in the active dossier to a concrete source page.

    ``None`` means no entity was requested.  An empty list means an explicit
    entity was requested but is absent from the selected report: broad ranking
    must not silently replace it with an unrelated page.
    """
    anchors = [item for item in [previous.document_anchor, updated.document_anchor] if item]
    anchors += [item for item in _anchor_candidates(updated.topic) if item not in anchors]
    if not anchors:
        return updated, None, None
    for anchor in anchors:
        evidence = retrieve_entity_evidence(updated.bank_id or "", updated.reporting_year or 0, anchor)
        if not evidence:
            continue
        first = evidence[0]
        scope = updated.document_scope
        if "parties liees" in _normalise(first.text):
            scope = "related_party_transactions"
        return updated.model_copy(update={
            "document_scope": scope,
            "document_anchor": anchor,
            "document_anchor_page": first.page_number,
        }), evidence, None
    return updated, [], anchors[0]


def _document_turn(message: str, context: ConversationContext, bank_id: str | None, year: int | None, *, continuation: bool, expand_scope: bool, document_scope: str | None) -> dict[str, Any]:
    topic = context.topic if continuation and context.topic else _topic(message)
    updated = _context(bank_id, year, mode="document", topic=topic, document_scope=document_scope, document_anchor=context.document_anchor, document_anchor_page=context.document_anchor_page)
    if not updated.bank_id or not updated.reporting_year:
        return _document_clarification(updated)
    if not reports_for([updated.bank_id], [updated.reporting_year]):
        return {
            "type": "clarification",
            "mode": "document",
            "context": updated.model_dump(),
            "missing_information": [],
            "message": "The corresponding official report is not yet available in the corpus.",
        }

    updated, anchor_evidence, missing_anchor = _resolve_document_anchor(updated, context)
    if missing_anchor:
        return {
            "type": "clarification",
            "mode": "document",
            "context": updated.model_dump(),
            "missing_information": [],
            "message": f"I cannot find the entity “{missing_anchor}” in this report. I will not associate it with pages that are merely close by wording.",
        }

    # “Les autres conventions après GSM” is already an expansion request even
    # when the user supplies bank and year in a separate second turn.
    expand_scope = expand_scope or (
        updated.document_scope == "related_party_transactions"
        and bool(EXPANSION_FOLLOW_UP.search(_normalise(topic)))
    )

    suffix = f"de {updated.bank_name} en {updated.reporting_year}"
    if continuation and topic:
        suffix += f" about {topic}"
    search_query = f"{message.strip()} {suffix}".strip()
    if expand_scope:
        # Keep the original note alongside the expanded legal-report scope. It lets
        # the answer explain the boundary between the two documents with evidence.
        # The anchor resolver can return later incidental mentions of the same
        # entity.  The first match is the primary source that established the
        # dossier; do not dilute this response with those later mentions.
        original_note = (anchor_evidence[:1] if anchor_evidence else retrieve_evidence(updated.bank_id, updated.reporting_year, topic, limit=1))
        expanded = retrieve_related_conventions(updated.bank_id, updated.reporting_year, limit=5)
        seen_pages: set[int] = set()
        evidence = [
            chunk
            for chunk in original_note + expanded
            if not (chunk.page_number in seen_pages or seen_pages.add(chunk.page_number))
        ]
    else:
        evidence = retrieve_evidence(
            updated.bank_id,
            updated.reporting_year,
            search_query,
            limit=3,
            include_neighbour_pages=True,
        )
    if not evidence:
        return {
            "type": "clarification",
            "mode": "document",
            "context": updated.model_dump(),
            "missing_information": [],
            "message": "I could not find a sufficiently relevant excerpt in this report. Rephrase the requested detail or widen the scope.",
        }
    analysis = _related_conventions_analysis(evidence, anchor=updated.document_anchor) if expand_scope else {
        "intent": "explanation",
        "scope_label": "Most relevant excerpts from the official report",
        "scope_explanation": "The answer is limited to the excerpts selected for this question.",
        "direct_answer": answer_from_evidence(search_query, evidence),
        "findings": [],
    }
    return {
        "type": "document",
        "mode": "document",
        "context": updated.model_dump(),
        # `answer` remains for clients already connected to the API. New clients
        # render `analysis`, whose fields make the reasoning and its boundaries clear.
        "answer": analysis["direct_answer"],
        "analysis": analysis,
        "evidence": [chunk.model_dump() for chunk in evidence],
    }


def _metric_turn(message: str, context: ConversationContext, bank_id: str | None, year: int | None, metric_id: str | None) -> dict[str, Any]:
    if bank_id is None:
        bank_id = context.bank_id
    if year is None:
        year = context.reporting_year
    if not bank_id or not year or not metric_id:
        assessment = assess_request(message)
        return {
            "type": "clarification",
            "mode": "metric",
            "context": _context(bank_id, year, mode="metric", metric_id=metric_id).model_dump(),
            "missing_information": assessment.missing_information,
            "message": assessment.reason,
        }
    if not reports_for([bank_id], [year]):
        return {
            "type": "clarification",
            "mode": "metric",
            "context": _context(bank_id, year, mode="metric", metric_id=metric_id).model_dump(),
            "missing_information": [],
            "message": "The corresponding official report is not yet available in the corpus.",
        }
    fact = auto_validated_fact(bank_id, year, metric_id)
    if fact is None:
        return {
            "type": "clarification",
            "mode": "metric",
            "context": _context(bank_id, year, mode="metric", metric_id=metric_id).model_dump(),
            "missing_information": [],
            "message": "This metric has not yet passed automatic validation for this report; no value is invented.",
        }
    answer = ReportedValueAnswer(
        metric_id=fact.metric_id,
        value=fact.value,
        currency=fact.currency,
        unit_scale=fact.unit_scale,
        reporting_year=fact.reporting_year,
        source_document=fact.source_path,
        page_number=fact.page_number,
        source_excerpt=fact.source_excerpt,
    )
    return {
        "type": "numeric",
        "mode": "metric",
        "context": _context(bank_id, year, mode="metric", metric_id=metric_id).model_dump(),
        **answer.model_dump(mode="json"),
    }


def answer_conversation_turn(message: str, context: ConversationContext) -> dict[str, Any]:
    """Route a turn using its live dossier before considering the metric catalog."""
    assessment = assess_request(message)
    bank_id = assessment.detected_banks[0] if len(assessment.detected_banks) == 1 else context.bank_id
    year = assessment.detected_years[0] if len(assessment.detected_years) == 1 else context.reporting_year
    metric_id = assessment.detected_metric or (context.metric_id if context.mode == "metric" else None)
    normalized_message = _normalise(message)
    documentary = bool(DOCUMENTARY_INTENT.search(normalized_message)) or (context.mode == "document" and metric_id is None)
    if documentary:
        explicit_related_scope = _related_party_scope(message)
        document_scope = "related_party_transactions" if explicit_related_scope else context.document_scope
        expand_scope = (
            context.mode == "document"
            and bool(EXPANSION_FOLLOW_UP.search(normalized_message))
            and document_scope == "related_party_transactions"
        )
        continuation = context.mode == "document" and (
            not bool(DOCUMENTARY_INTENT.search(normalized_message))
            or expand_scope
            or bool(REFERENCE_FOLLOW_UP.search(normalized_message))
        )
        return _document_turn(message, context, bank_id, year, continuation=continuation, expand_scope=expand_scope, document_scope=document_scope)
    return _metric_turn(message, context, bank_id, year, metric_id)
