"""Conversation-first routing for automatically validated metrics and documentary analysis."""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from myfinance_agent_docs.catalog import (
    assessment_metrics,
    bank_definitions,
    documentary_glossary,
    reports_for,
)
from myfinance_agent_docs.corpus import (
    retrieve_entity_evidence,
    retrieve_evidence,
    retrieve_related_conventions,
)
from myfinance_agent_docs.facts import auto_validated_fact, source_matched_fact
from myfinance_agent_market.market_watch_reader import (
    MarketWatchUnavailable,
    current_market_quote,
    current_market_quotes,
    current_market_summary,
    historical_market_performance,
    historical_market_performance_range,
)
from myfinance_contracts import ConversationContext, ReportedValueAnswer

from myfinance_orchestrator.assessment import assess_request
from myfinance_orchestrator.evidence_synthesis import answer_from_evidence
from myfinance_orchestrator.general_sources import sources_for_general_question
from myfinance_orchestrator.model_provider import USE_LLM, complete, json_object

logger = logging.getLogger(__name__)

# Exposed by the local status endpoint so a browser test can prove which
# conversation state machine is actually running after a reload.
ROUTER_REVISION = "turn-planner-v3"

_PROFILE_FILLER_WORDS = {
    "a", "about", "are", "bank", "ce", "cest", "comment", "describe", "est", "is",
    "la", "le", "moi", "me", "parle", "quoi", "que", "quel", "quelle", "qui", "tell",
    "the", "this", "un", "une", "what", "who", "you",
}
_DOCUMENT_REQUEST_CUES = {
    "accounting standard", "accounting standards", "accounting policy", "accounting policies",
    "credit risk", "related party", "related parties", "transaction", "transactions",
    "norme comptable", "normes comptables", "politique comptable", "politiques comptables",
    "risque de credit", "risques de credit", "partie liee", "parties liees",
    "convention", "conventions", "portefeuille", "provision", "creance", "liquidite",
}

_PLAN_OPERATIONS = {
    "metric_lookup", "compare", "comparison_analysis", "metric_interpretation",
    "multi_metric_analysis", "documentary", "bank_profile", "general_education", "market", "clarify",
}
_BANK_SCOPES = {"explicit", "active_metric", "active_pair", "active_comparison", "active_market", "all_available", "none"}
_VALUE_SCOPES = {"explicit", "active", "none"}
_DOCUMENT_ACTIONS = {"new", "continue", "expand_scope"}
_DOCUMENT_SCOPES = {"none", "related_party_transactions"}
_SEMANTIC_BANK_SCOPES = {"all_available", "explicit", "context", "none"}
_SEMANTIC_ANALYSIS_SCOPES = {"all_discussed_metrics", "active_metric", "none"}
_AGENT_ROUTES = {"reporting", "market", "general_education", "clarify"}
_MARKET_REQUEST_KINDS = {
    "current_quote", "market_overview", "historical_performance",
    "instrument_activity", "event_explanation", "clarify",
}
_DOCUMENT_FOLLOWUP_FILLERS = {
    "about", "again", "are", "can", "ce", "cela", "comment", "do", "does", "en", "encore",
    "est", "etre", "how", "il", "is", "le", "les", "la", "no", "non", "ok", "okay", "oui",
    "please", "pourquoi", "quoi", "que", "qui", "really", "sure", "sur", "tu", "vous", "what",
    "why", "yes", "you",
}
_GENERAL_LOCATION_FOLLOWUP_PREFIXES = {("and", "in"), ("et", "en"), ("in",), ("en",)}
_GENERAL_SOURCE_CITATION = re.compile(r"\[([a-z0-9_-]+)\]")
_GENERAL_INDEX_CUES = re.compile(r"\b(?:index|indice|bourse|stock[ -]market)\b", re.IGNORECASE)
_ALL_AVAILABLE_BANKS_CUES = re.compile(
    r"\b(?:all (?:available |supported )?banks|every (?:available |supported )?bank|"
    r"toutes? les banques(?: disponibles?)?)\b",
    re.IGNORECASE,
)
_SOURCE_BYPASS_CUES = (
    "without citing", "without a citation", "without citing the report", "without a source", "without sources",
    "without the report", "sans citer", "sans citation", "sans source", "sans rapport",
    "ignore the source", "ignore the sources", "ignore sources", "ignore les sources", "ignore les rapports",
)
_PERSONAL_ACCOUNT_CUES = (
    "my bank account", "my account balance", "my account", "mon compte bancaire", "mon compte", "solde de mon compte",
)
_UNSUPPORTED_RANKING_CUES = (
    "safest", "most safe", "safer bank", "best bank", "plus sure", "plus sûre", "la meilleure banque",
)
_UNSOURCED_CURRENCY_CONVERSION = re.compile(
    r"\b(?:convert(?:ed|ion)?|conversion|exchange rate|currency|taux de change|convertir|conversion)\b"
    r"|\b(?:in|en)\s+(?:us\s*)?(?:dollars?|usd|euros?|eur|pounds?|gbp|livres?)\b",
    re.IGNORECASE,
)
_OUT_OF_SCOPE_METRIC_CUES = re.compile(r"\b(?:bitcoin|crypto(?:currency)?|blockchain token)\b", re.IGNORECASE)
_FINANCIAL_STATEMENT_ACCESS_CUES = re.compile(
    r"\b(?:financial statements?|annual reports?|financial reports?|comptes financiers?|rapport annuel|rapport financier)\b",
    re.IGNORECASE,
)
_CURRENT_QUOTE_CUES = re.compile(
    r"\b(?:current|latest|live|today'?s)\s+(?:share|stock)s?\s+(?:price|quote)s?\b"
    r"|\b(?:share|stock)s?\s+(?:price|quote)s?\b"
    r"|\b(?:cours|cotation|prix)\s+(?:actuel|du jour|de l[' ]?action|action)\b",
    re.IGNORECASE,
)
_BANK_COMPARISON_CUES = re.compile(r"\b(?:compare|comparison|comparer|comparaison)\b", re.IGNORECASE)
_BANK_REFERENCE_STOPWORDS = {
    "a", "all", "an", "and", "available", "bank", "banque", "banques", "banks", "d", "de", "des", "du",
    "et", "every", "l", "la", "le", "les", "of", "or", "ou", "supported", "the", "un", "une",
}


def _topic(message: str) -> str:
    return re.sub(r"\s+", " ", message).strip(" ?!.")


def _is_explicit_current_quote_request(message: str) -> bool:
    """Recognise a current quote without depending on the optional LLM router."""
    return bool(_CURRENT_QUOTE_CUES.search(_normalise(message)))


def _requests_bank_comparison(message: str) -> bool:
    """Recognise an explicit comparison while leaving its financial criterion open."""
    return bool(_BANK_COMPARISON_CUES.search(_normalise(message)))


def _safety_clarification(message: str, context: ConversationContext, assessment: Any) -> dict[str, Any] | None:
    """Stop unsafe requests before a planner or metric lookup can emit a value."""

    normalised = _normalise(message)
    if any(cue in normalised for cue in _SOURCE_BYPASS_CUES):
        message = "I can provide only a verified value with the official report and page reference. Would you like the sourced figure?"
    elif any(cue in normalised for cue in _PERSONAL_ACCOUNT_CUES):
        message = "I do not have access to personal bank-account data. I can help with public information from official bank reports instead."
    elif _UNSOURCED_CURRENCY_CONVERSION.search(normalised):
        message = "I can report the value in the official report's stated currency and unit, but I cannot convert it without a dated, official exchange-rate source."
    elif assessment.detected_metric is None and any(cue in normalised for cue in _UNSUPPORTED_RANKING_CUES):
        message = "I cannot rank banks as “safest” from annual reports alone. Please provide a defined, sourceable criterion, such as a capital ratio, non-performing loans or a named rating."
    else:
        return None
    return {
        "type": "clarification",
        "mode": context.mode,
        "context": context.model_dump(),
        "missing_information": [],
        "message": message,
    }


def _is_short_general_location_followup(message: str, context: ConversationContext, assessment: Any) -> bool:
    """Keep a terse country follow-up in an existing general explanation."""
    if (
        context.mode != "general"
        or assessment.detected_banks
        or assessment.detected_metric
        or assessment.detected_years
    ):
        return False
    words = tuple(re.findall(r"[a-zà-ÿ]+", message.casefold()))
    if not 2 <= len(words) <= 4:
        return False
    return any(words[:len(prefix)] == prefix for prefix in _GENERAL_LOCATION_FOLLOWUP_PREFIXES)


def _has_single_metric_context(context: ConversationContext) -> bool:
    return bool(
        context.mode == "metric"
        and context.bank_id
        and context.reporting_year
        and context.metric_id
        and len(context.metric_bank_ids) < 2
    )


def _requests_all_available_banks(message: str) -> bool:
    """Recognise the unambiguous expansion of a comparison to every bank.

    This is deliberately deterministic: a mapped financial metric must retain
    its validated-facts route, while an explicit request for every supported
    bank still has to become a comparison.
    """
    return bool(_ALL_AVAILABLE_BANKS_CUES.search(message))


def _conversation_router_enabled() -> bool:
    """Keep the conversational classifier opt-in when no model is configured."""
    default = "1" if os.environ.get("GROQ_API_KEY") or USE_LLM else "0"
    return os.environ.get("MYFINANCE_CONVERSATION_ROUTER", default).strip().lower() in {"1", "true", "yes"}


def _classify_conversation_intent(message: str, context: ConversationContext, assessment: Any | None = None) -> dict[str, str] | None:
    """Ask the LLM for a closed, metadata-only turn plan."""
    if not _conversation_router_enabled():
        return None
    payload = json_object(
        """You are the turn planner for a source-locked financial assistant.
Return JSON only, exactly in this schema:
{"operation":"metric_lookup|compare|comparison_analysis|multi_metric_analysis|metric_interpretation|documentary|bank_profile|general_education|market|clarify","bank_scope":"explicit|active_metric|active_pair|active_comparison|active_market|all_available|none","period_scope":"explicit|active|none","metric_scope":"explicit|active|none","document_action":"new|continue|expand_scope","document_scope":"none|related_party_transactions","clarification":""}

You select an operation and references only; you never answer, calculate, inspect a report, invent a bank, or invent a period.
Use `all_available` when the user expands a comparison to every supported bank. Use `active_pair` for pronouns such as “them” that refer to the two banks just discussed. Use `metric_interpretation` for a qualitative question about one active result. Use `comparison_analysis` only to interpret an already active comparison.
Use `market` for a traded share price, quote, return, traded volume, market capitalisation, stock-market movement or market disclosure. A financial-statement metric such as PNB, deposits or net income remains `metric_lookup`/`compare`, not `market`.
Use `documentary` for the content, notes, accounting policies, risks, portfolio composition or statements in a specified financial report. The documentary agent must not answer a market request.
If essential data cannot be resolved from explicit request or active context, use `clarify` and ask one concise question in English.

Resolution examples:
- If a metric and year are active, “compare all banks available” means operation `compare`, bank_scope `all_available`, period_scope `active`, metric_scope `active`.
- If two metric banks are active, “compare the two banks” means operation `compare`, bank_scope `active_pair`, period_scope `active`, metric_scope `active`.
- If a comparison is already active, a question about the size or meaning of its gap means `comparison_analysis`; it does not change the bank scope.
- If the user asks for an analysis of all metrics previously discussed in an active comparison dossier, use `multi_metric_analysis`.
- Do not use `clarify` when the active context already supplies every missing bank, period, or metric reference.

Active context (metadata only):
""" + context.model_dump_json() + "\n\nDeterministically detected request data (candidates only):\n" + (
            assessment.model_dump_json() if assessment is not None else "{}"
        ) + "\n\nUser message:\n" + message,
        max_tokens=120,
    )
    if not payload:
        return None
    operation = payload.get("operation", payload.get("intent"))
    if operation == "metric":
        operation = "metric_lookup"
    if operation not in _PLAN_OPERATIONS:
        return None
    bank_scope = payload.get("bank_scope", "none")
    period_scope = payload.get("period_scope", "none")
    metric_scope = payload.get("metric_scope", "none")
    document_action = payload.get("document_action", "new")
    document_scope = payload.get("document_scope", "none")
    clarification = payload.get("clarification", "")
    if bank_scope not in _BANK_SCOPES or period_scope not in _VALUE_SCOPES or metric_scope not in _VALUE_SCOPES or document_action not in _DOCUMENT_ACTIONS or document_scope not in _DOCUMENT_SCOPES:
        return None
    if not isinstance(clarification, str):
        clarification = ""
    return {
        "operation": operation,
        "bank_scope": bank_scope,
        "period_scope": period_scope,
        "metric_scope": metric_scope,
        "document_action": document_action,
        "document_scope": document_scope,
        "clarification": " ".join(clarification.split())[:500],
    }


def _classify_agent_route(message: str, context: ConversationContext) -> str | None:
    """Let a narrow LLM router select the responsible agent before planning a turn.

    This is intentionally independent of extraction and of report retrieval.
    Its output controls a domain boundary only; the selected agent still has to
    establish evidence and may refuse to answer.
    """
    if not _conversation_router_enabled():
        return None
    payload = json_object(
        """You are the top-level router for MyFinance. Select exactly one agent.
Return JSON only: {"agent":"reporting|market|general_education|clarify"}.

- reporting: financial-report facts, financial statements, report notes, bank financial metrics, or comparisons based on annual reports.
- market: share price, stock/share performance, quoted return, trading volume, market capitalisation, exchange trading, market disclosure or historical market data.
- general_education: a general definition or learning question that is not about a particular bank, report or current market observation.
- clarify: the request cannot be assigned safely.

Do not answer the user, infer a value, or inspect any source. A question about a bank's stock belongs to market even when it names a year.

Conversation context (metadata only):
""" + context.model_dump_json() + "\n\nUser message:\n" + message,
        # The deployed reasoning model needs room to decide before returning
        # its very short JSON output. This router stays cheap because it never
        # receives PDF content.
        max_tokens=240,
    )
    agent = payload.get("agent") if payload else None
    return agent if agent in _AGENT_ROUTES else None


def _classify_market_request(message: str, context: ConversationContext) -> str | None:
    """Select the market capability required, independently of report retrieval.

    The model may select only a capability; a deterministic boundary below
    decides whether the official source currently supplies that capability.
    """
    if not _conversation_router_enabled():
        return None
    payload = json_object(
        """You route a market question to one data capability. Return JSON only:
{"market_request":"current_quote|market_overview|historical_performance|instrument_activity|event_explanation|clarify"}.

- current_quote: current share price, current session change, or a comparison of current share prices.
- market_overview: whole Bourse de Tunis session statistics, market breadth, total turnover, total transactions or market capitalisation.
- historical_performance: price evolution, return, chart or comparison over a dated period.
- instrument_activity: a bank share's traded volume, transaction count, high/low, order book, or liquidity.
- event_explanation: why a stock moved or what official market announcement affected it.
- clarify: no market data capability is identifiable.

Do not answer, calculate, access a source or invent a data point. Do not route a bank-report metric to market.
Context metadata only:\n""" + context.model_dump_json() + "\n\nUser message:\n" + message,
        max_tokens=160,
    )
    kind = payload.get("market_request") if payload else None
    return kind if kind in _MARKET_REQUEST_KINDS else None


def _classify_requested_bank_scope(message: str) -> str | None:
    """Classify the requested bank set independently from the full turn plan.

    Scope controls which reports are opened, so it is a safety-critical slot.
    A narrow, context-free LLM decision is less prone to inherit the previous
    single-bank dossier than a general planner that decides every turn field at
    once.  It never identifies or invents banks.
    """
    if not _conversation_router_enabled():
        return None
    payload = json_object(
        """Classify only the bank scope explicitly requested by this user message.
Return JSON only: {"bank_scope":"all_available|explicit|context|none"}.

Definitions:
- all_available: the user asks to include every available/supported bank or the entire set.
- explicit: the user names one or more banks.
- context: the user refers to a previously discussed bank or pair without expanding the set.
- none: no bank set is requested or implied.

Do not use an active conversation, do not require a bank name, do not answer the question, and do not infer a financial value.

User message:
""" + message,
        # Reasoning-capable models can spend tokens before emitting the tiny
        # JSON object; starving this call made a missing decision look like an
        # ambiguous one.
        max_tokens=160,
    )
    scope = payload.get("bank_scope") if payload else None
    return scope if scope in _SEMANTIC_BANK_SCOPES else None


def _classify_requested_analysis_scope(message: str, context: ConversationContext) -> str | None:
    """Resolve whether an analysis refers to one metric or the retained set."""
    if not _conversation_router_enabled() or len(context.comparison_metric_ids) < 2:
        return None
    payload = json_object(
        """Classify only the requested scope of a financial comparison analysis.
Return JSON only: {"analysis_scope":"all_discussed_metrics|active_metric|none"}.

- all_discussed_metrics: the user asks to analyse, review, explain or compare every metric previously discussed.
- active_metric: the user asks about the current metric only.
- none: the message is not an analysis request.

Do not answer the question and do not infer financial values.
Previously compared metrics: """ + ", ".join(context.comparison_metric_ids) + "\n\nUser message:\n" + message,
        max_tokens=160,
    )
    scope = payload.get("analysis_scope") if payload else None
    return scope if scope in _SEMANTIC_ANALYSIS_SCOPES else None


def _default_scope(operation: str, context: ConversationContext, assessment: Any) -> dict[str, str]:
    """Resolve a safe default plan only from structure, never from phrasing."""
    detected_banks = assessment.detected_banks
    if operation == "compare":
        bank_scope = "explicit" if len(detected_banks) >= 2 else "active_comparison" if context.mode == "comparison" else "active_pair"
    elif operation == "metric_lookup":
        bank_scope = "explicit" if len(detected_banks) == 1 else "active_metric"
    elif operation == "market":
        bank_scope = (
            "explicit"
            if detected_banks
            else "active_market"
            if context.mode == "market" and context.market_bank_ids
            else "active_metric"
            if context.bank_id
            else "none"
        )
    elif operation in {"documentary", "bank_profile"}:
        bank_scope = "explicit" if len(detected_banks) == 1 else "active_metric" if context.bank_id else "none"
    else:
        bank_scope = "none"
    return {
        "operation": operation,
        "bank_scope": bank_scope,
        "period_scope": "explicit" if assessment.detected_years else "active",
        "metric_scope": "explicit" if assessment.detected_metric else "active",
        "document_action": "continue" if context.mode == "document" else "new",
        "document_scope": context.document_scope or "none",
        "clarification": "",
    }


def _fallback_turn_plan(message: str, context: ConversationContext, assessment: Any) -> dict[str, str]:
    """Deterministic fallback for explicit data and existing state transitions.

    It intentionally does not interpret user wording. Free-form requests require
    the LLM planner; the fallback can only follow unambiguous structured data.
    """
    if assessment.detected_metric and len(assessment.detected_banks) >= 2:
        return _default_scope("compare", context, assessment)
    if assessment.detected_metric and context.mode == "comparison" and not assessment.detected_banks:
        return _default_scope("compare", context, assessment)
    if assessment.detected_metric:
        return _default_scope("metric_lookup", context, assessment)
    if len(assessment.detected_banks) == 1:
        if _profile_bank_id(
            message, bank_ids=assessment.detected_banks,
            year=assessment.detected_years[0] if len(assessment.detected_years) == 1 else None,
            metric_id=assessment.detected_metric,
        ):
            return _default_scope("bank_profile", context, assessment)
        if context.mode == "metric" and context.metric_id:
            return _default_scope("metric_lookup", context, assessment)
        if _is_explicit_documentary_request(message, assessment):
            return _default_scope("documentary", context, assessment)
        # Selecting the documentary or market agent is a semantic decision.
        # If the route model is unavailable, do not guess one based merely on
        # a bank name or year: asking a clarification is safer than opening an
        # unrelated report.
        return _default_scope("clarify", context, assessment)
    if context.mode == "comparison":
        return _default_scope("comparison_analysis", context, assessment)
    if (
        context.mode == "metric"
        and context.bank_id
        and context.metric_id
        and context.reporting_year is None
        and len(assessment.detected_years) == 1
    ):
        return _default_scope("metric_lookup", context, assessment)
    if context.mode == "document":
        return _default_scope("documentary", context, assessment)
    if context.mode == "general":
        return _default_scope("general_education", context, assessment)
    if context.mode == "market":
        return _default_scope("market", context, assessment)
    return _default_scope("clarify", context, assessment)


def _turn_plan(
    message: str,
    context: ConversationContext,
    assessment: Any,
    routing_message: str | None = None,
) -> dict[str, str]:
    """Return one validated operation for this turn, or a structural fallback."""
    route_message = routing_message or message
    profile_bank_id = _profile_bank_id(
        message, bank_ids=assessment.detected_banks,
        year=assessment.detected_years[0] if len(assessment.detected_years) == 1 else None,
        metric_id=assessment.detected_metric,
    )
    if profile_bank_id and (context.mode != "metric" or _is_explicit_identity_question(message)):
        return _validate_turn_plan(
            _default_scope("bank_profile", context, assessment),
            context,
            assessment,
            preserve_identity=True,
        )
    if _is_explicit_documentary_request(message, assessment):
        return _validate_turn_plan(_default_scope("documentary", context, assessment), context, assessment)
    if _is_short_general_location_followup(message, context, assessment):
        return _validate_turn_plan(_default_scope("general_education", context, assessment), context, assessment)
    requested_bank_scope = _classify_requested_bank_scope(route_message)
    requested_analysis_scope = _classify_requested_analysis_scope(route_message, context)

    # An explicit, mapped statement metric (such as PNB) is answered from the
    # validated facts catalogue. It must precede semantic agent selection:
    # the latter is for unstructured documentary questions and cannot replace
    # a source-validated financial value with a note lookup.
    if assessment.detected_metric:
        fallback = _fallback_turn_plan(message, context, assessment)
        if requested_bank_scope == "all_available" or _requests_all_available_banks(route_message):
            fallback = {**fallback, "operation": "compare", "bank_scope": "all_available"}
        if requested_analysis_scope == "all_discussed_metrics":
            fallback = {**fallback, "operation": "multi_metric_analysis"}
        validated = _validate_turn_plan(fallback, context, assessment)
        logger.info("turn_plan source=validated_metric message=%r validated=%s", message, validated)
        return validated

    # A question about a registered official index is general education, not a
    # request for a listed-bank quote.  This also supports one question naming
    # several countries, each with its own approved official reference.
    if _GENERAL_INDEX_CUES.search(route_message) and sources_for_general_question(route_message, context.topic):
        return _validate_turn_plan(_default_scope("general_education", context, assessment), context, assessment)

    # A current share-price request has a single, safe data domain.  It must
    # stay available when the optional Groq router is unavailable or exhausted.
    if _is_explicit_current_quote_request(route_message):
        return _validate_turn_plan(_default_scope("market", context, assessment), context, assessment)

    agent_route = _classify_agent_route(route_message, context)
    proposed = _classify_conversation_intent(route_message, context, assessment)
    # Agent selection is the primary domain boundary. A market request may
    # never be downgraded to a reporting/documentary turn by the richer
    # planner; it contains different source and evidence rules.
    if agent_route == "market":
        return _validate_turn_plan(_default_scope("market", context, assessment), context, assessment)
    if agent_route == "general_education":
        return _validate_turn_plan(_default_scope("general_education", context, assessment), context, assessment)
    if agent_route == "reporting" and (proposed is None or proposed.get("operation") == "clarify"):
        return _validate_turn_plan(_default_scope("documentary", context, assessment), context, assessment)
    if proposed is not None:
        operation = proposed.get("operation", proposed.get("intent"))
        if operation == "metric":
            operation = "metric_lookup"
        if operation in _PLAN_OPERATIONS:
            plan = _default_scope(operation, context, assessment)
            for key in ("bank_scope", "period_scope", "metric_scope", "document_action", "document_scope", "clarification"):
                if key in proposed:
                    plan[key] = proposed[key]
            if requested_bank_scope == "all_available":
                plan["bank_scope"] = "all_available"
            if requested_analysis_scope == "all_discussed_metrics":
                plan["operation"] = "multi_metric_analysis"
            validated = _validate_turn_plan(plan, context, assessment)
            logger.info(
                "turn_plan source=llm message=%r bank_scope_guard=%s analysis_scope_guard=%s proposed=%s validated=%s",
                message,
                requested_bank_scope,
                requested_analysis_scope,
                proposed,
                validated,
            )
            return validated
    fallback = _fallback_turn_plan(message, context, assessment)
    if requested_bank_scope == "all_available" or _requests_all_available_banks(route_message):
        fallback = {**fallback, "operation": "compare", "bank_scope": "all_available"}
    if requested_analysis_scope == "all_discussed_metrics":
        fallback = {**fallback, "operation": "multi_metric_analysis"}
    validated = _validate_turn_plan(fallback, context, assessment)
    logger.info(
        "turn_plan source=fallback message=%r validated=%s",
        message,
        validated,
    )
    return validated


def _validate_turn_plan(
    plan: dict[str, str],
    context: ConversationContext,
    assessment: Any,
    *,
    preserve_identity: bool = False,
) -> dict[str, str]:
    """Enforce state transitions independently from the LLM's wording judgment."""
    # Scope and operation form one state-machine transition. A request that
    # changes the bank set cannot be an interpretation of the old comparison.
    if plan["bank_scope"] in {"all_available", "active_pair"}:
        plan = {**plan, "operation": "compare"}
    if plan["operation"] == "compare":
        if plan["bank_scope"] == "none":
            return {**_default_scope("clarify", context, assessment), "clarification": "Please specify the banks to compare."}
        if plan["period_scope"] == "explicit" and not assessment.detected_years and context.reporting_year:
            plan = {**plan, "period_scope": "active"}
        if plan["metric_scope"] == "explicit" and assessment.detected_metric is None and context.metric_id:
            plan = {**plan, "metric_scope": "active"}
    if (
        plan["operation"] == "bank_profile"
        and context.mode == "metric"
        and context.metric_id
        and len(assessment.detected_banks) == 1
        and not assessment.detected_years
        and assessment.detected_metric is None
        and not preserve_identity
    ):
        return {
            **_default_scope("metric_lookup", context, assessment),
            "bank_scope": "explicit",
            "period_scope": "active",
            "metric_scope": "active",
        }
    if plan["operation"] == "metric_interpretation" and not _has_single_metric_context(context):
        return {**_default_scope("clarify", context, assessment), "clarification": "Please select one reported value before asking for an interpretation."}
    if (
        plan["operation"] == "comparison_analysis"
        and context.mode == "comparison"
        and (len(context.comparison_bank_ids) < 2 or context.reporting_year is None or context.metric_id is None)
        and (assessment.detected_years or assessment.detected_metric)
    ):
        # A comparison clarification is a partially filled dossier.  A later
        # year or metric supplies a missing slot; it cannot be an analysis of
        # values that do not exist yet, even if the LLM calls it one.
        return {
            **_default_scope("compare", context, assessment),
            "bank_scope": "active_comparison",
            "period_scope": "explicit" if assessment.detected_years else "active",
            "metric_scope": "explicit" if assessment.detected_metric else "active",
        }
    if plan["operation"] == "multi_metric_analysis" and (
        context.mode != "comparison" or len(context.comparison_metric_ids) < 2
    ):
        return {
            **_default_scope("clarify", context, assessment),
            "clarification": "Please compare at least two metrics before requesting a multi-metric analysis.",
        }
    if plan["operation"] == "comparison_analysis" and context.mode != "comparison":
        return {**_default_scope("clarify", context, assessment), "clarification": "Please create a comparison before asking for its interpretation."}
    if plan["operation"] == "market" and plan["bank_scope"] == "none" and context.mode == "market" and context.market_bank_ids:
        return {**plan, "bank_scope": "active_market"}
    return plan


def _plan_banks(plan: dict[str, str], context: ConversationContext, assessment: Any) -> list[str]:
    scope = plan["bank_scope"]
    if scope == "explicit":
        return list(assessment.detected_banks)
    if scope == "active_metric":
        return [context.bank_id] if context.bank_id else []
    if scope == "active_pair":
        return list(context.metric_bank_ids)
    if scope == "active_comparison":
        return list(context.comparison_bank_ids)
    if scope == "active_market":
        return list(context.market_bank_ids)
    if scope == "all_available":
        return list(bank_definitions())
    return []


def _plan_year(plan: dict[str, str], context: ConversationContext, assessment: Any) -> int | None:
    return assessment.detected_years[0] if plan["period_scope"] == "explicit" and len(assessment.detected_years) == 1 else context.reporting_year


def _plan_metric(plan: dict[str, str], context: ConversationContext, assessment: Any) -> str | None:
    return assessment.detected_metric if plan["metric_scope"] == "explicit" else context.metric_id


def _general_education_turn(message: str, context: ConversationContext) -> dict[str, Any]:
    """Generate a general explanation without treating it as a report finding."""
    sources = sources_for_general_question(message, context.topic)
    if sources:
        source_packet = "\n".join(
            f"[{source['source_id']}] {source['title']}\n"
            f"URL: {source['url']}\n"
            f"Verified context: {source['supported_context']}"
            for source in sources
        )
        answer = complete(
            """You are MyFinance's general financial-literacy guide. Answer in the user's language.

Use only the official source packet below. Do not add facts, figures, dates or
claims that it does not support. Address every country or index asked about and
cite each factual statement with its source identifier in square brackets, for
example [euronext_cac40]. If the packet is insufficient, say so instead of guessing.

Official source packet:
""" + source_packet + """

User question:
""" + message,
            max_tokens=220,
        )
        cited_sources = _cited_general_sources(answer, sources)
        if answer and cited_sources:
            return _general_answer(answer, message, context, sources=cited_sources)
        if _general_sources_required():
            return _general_source_required_answer(message, context)
    elif _general_sources_required():
        return _general_source_required_answer(message, context)

    answer = complete(
        """You are MyFinance's general financial-literacy guide. Answer the user's question clearly and naturally in English, even if the question is written in another language.

This is general education, not analysis of a bank report. Do not claim to have read a report, do not cite sources you were not given, do not give personalised investment advice, and do not make current market or company-specific claims. If the question cannot be answered safely as general education, ask one concise clarifying question instead.

The user may be continuing a short general conversation. Use the topic and your previous answer to resolve pronouns and short follow-ups such as “only banks?”, “financial reports”, or “annual ones”. Do not ask them to repeat the subject when this context already answers it.

General conversation topic:
""" + (context.topic or "None yet") + """

Previous answer:
""" + (context.general_last_answer or "None yet") + """

User question:
""" + message,
        max_tokens=220,
    )
    compact_answer = " ".join(answer.split()) if answer else ""
    if len(compact_answer) < 20 or len(compact_answer) > 1_400:
        return {
            "type": "clarification",
            "mode": "general",
            "context": ConversationContext(
                mode="general",
                topic=context.topic or _topic(message),
                general_last_answer=context.general_last_answer,
            ).model_dump(),
            "missing_information": [],
            "message": "The general conversation assistant is unavailable. Please try again shortly.",
        }
    return {
        "type": "general",
        "mode": "general",
        "context": ConversationContext(
            mode="general",
            topic=context.topic or _topic(message),
            general_last_answer=compact_answer,
        ).model_dump(),
        "answer": compact_answer,
        "topic": "general_education",
    }


def _general_sources_required() -> bool:
    return os.environ.get("MYFINANCE_REQUIRE_GENERAL_SOURCES", "0").strip().lower() in {"1", "true", "yes"}


def _cited_general_sources(answer: str | None, sources: list[dict[str, str]]) -> list[dict[str, str]]:
    if not answer:
        return []
    allowed = {source["source_id"]: source for source in sources}
    cited_ids = _GENERAL_SOURCE_CITATION.findall(answer.casefold())
    return [allowed[source_id] for source_id in dict.fromkeys(cited_ids) if source_id in allowed]


def _general_source_required_answer(message: str, context: ConversationContext) -> dict[str, Any]:
    return {
        "type": "general",
        "mode": "general",
        "context": ConversationContext(
            mode="general",
            topic=context.topic or _topic(message),
            general_last_answer=context.general_last_answer,
        ).model_dump(),
        "answer": "I cannot provide a verified answer because no approved official source is available for this topic yet.",
        "topic": "general_education",
        "source_status": "official_source_required",
        "sources": [],
    }


def _general_answer(
    answer: str,
    message: str,
    context: ConversationContext,
    *,
    sources: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    visible_answer = _GENERAL_SOURCE_CITATION.sub("", answer) if sources else answer
    compact_answer = " ".join(visible_answer.split())
    return {
        "type": "general",
        "mode": "general",
        "context": ConversationContext(
            mode="general",
            topic=context.topic or _topic(message),
            general_last_answer=compact_answer,
        ).model_dump(),
        "answer": compact_answer,
        "topic": "general_education",
        "sources": sources or [],
    }


def _market_turn(
    context: ConversationContext,
    bank_ids: list[str],
    year: int | None,
    request_kind: str = "current_quote",
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Read current Market Watch quotes; never substitute a report value."""
    next_context = ConversationContext(
        mode="market",
        market_bank_ids=bank_ids,
        topic="market_data",
    )
    if request_kind == "market_overview":
        try:
            summary = current_market_summary()
        except MarketWatchUnavailable as error:
            return {
                "type": "market_notice",
                "mode": "market",
                "context": next_context.model_dump(),
                "title": "Market summary unavailable",
                "message": f"I could not read the official Market Watch session summary right now: {error}",
            }
        return {
            "type": "market_overview",
            "mode": "market",
            "context": next_context.model_dump(),
            "summary": summary,
        }
    if request_kind == "historical_performance":
        period_year = int(start_date[:4]) if start_date else year
        if len(bank_ids) != 1 or period_year is None:
            return {
                "type": "market_notice",
                "mode": "market",
                "context": next_context.model_dump(),
                "title": "Choose one bank and a year",
                "message": "Historical performance needs one listed bank and a calendar year, for example: “How did BIAT stock perform in 2026?”",
            }
        try:
            performance = _historical_performance(bank_ids[0], period_year, start_date, end_date)
        except MarketWatchUnavailable as error:
            return {
                "type": "market_notice",
                "mode": "market",
                "context": next_context.model_dump(),
                "title": "Historical data unavailable",
                "message": f"I could not read the official historical series for that request: {error}",
            }
        return {
            "type": "market_performance",
            "mode": "market",
            "context": next_context.model_dump(),
            "performance": performance,
        }
    if request_kind in {"instrument_activity", "event_explanation"}:
        if request_kind == "instrument_activity" and len(bank_ids) == 1 and year is not None:
            try:
                performance = _historical_performance(bank_ids[0], year, None, None)
            except MarketWatchUnavailable as error:
                return {
                    "type": "market_notice", "mode": "market", "context": next_context.model_dump(),
                    "title": "Instrument activity unavailable",
                    "message": f"I could not read the official activity series for that request: {error}",
                }
            latest = performance["points"][-1]
            available = {
                key: latest[key]
                for key in ("volume", "turnover_tnd", "transactions", "market_capitalization_md")
                if latest.get(key) is not None
            }
            if available:
                return {
                    "type": "market_activity", "mode": "market", "context": next_context.model_dump(),
                    "activity": {
                        "bank_id": performance["bank_id"], "bank_name": performance["bank_name"],
                        "mnemonic": performance["mnemonic"], "currency": performance["currency"],
                        "observation_date": latest.get("date"), "metrics": available,
                        "source_url": performance["source_url"], "retrieved_at": performance["retrieved_at"],
                        "series_origin": performance.get("series_origin", "official_history"),
                    },
                }
        titles = {
            "instrument_activity": "Instrument activity reader pending",
            "event_explanation": "Event-analysis reader pending",
        }
        return {
            "type": "market_notice",
            "mode": "market",
            "context": next_context.model_dump(),
            "title": titles[request_kind],
            "message": "This question needs one listed bank and a calendar year, or an issuer-publication reader. The current Market Watch reader only returns activity when the official historical series supplies it, so no conclusion is inferred otherwise.",
        }
    if not bank_ids:
        return {
            "type": "market_notice",
            "mode": "market",
            "context": next_context.model_dump(),
            "title": "Choose a listed bank",
            "message": "Please name a listed bank for a current Market Watch quote.",
        }
    if year is not None:
        return {
            "type": "market_notice",
            "mode": "market",
            "context": next_context.model_dump(),
            "title": "Historical quote not available",
            "message": "The current Market Watch reader cannot yet answer a historical year. Please ask for the current quote or provide an official historical export.",
        }
    try:
        if len(bank_ids) > 1:
            quotes = current_market_quotes(bank_ids)
            return {
                "type": "market_comparison",
                "mode": "market",
                "context": next_context.model_dump(),
                "quotes": sorted(quotes, key=lambda quote: quote["price"], reverse=True),
                "answer": _market_comparison_summary(quotes),
            }
        quote = current_market_quote(bank_ids[0])
    except MarketWatchUnavailable as error:
        return {
            "type": "market_notice",
            "mode": "market",
            "context": next_context.model_dump(),
            "title": "Official quote unavailable",
            "message": f"I could not read the official Market Watch quote right now: {error}",
        }
    return {
        "type": "market_quote",
        "mode": "market",
        "context": next_context.model_dump(),
        "quote": quote,
        "answer": _market_quote_summary(quote),
    }


def _historical_performance(
    bank_id: str, year: int, start_date: str | None, end_date: str | None,
) -> dict[str, Any]:
    if start_date and end_date and start_date[:4] != end_date[:4]:
        return historical_market_performance_range(bank_id, start_date, end_date)
    if start_date or end_date:
        return historical_market_performance(bank_id, year, start_date=start_date, end_date=end_date)
    return historical_market_performance(bank_id, year)


def _market_date_range(message: str) -> tuple[str | None, str | None]:
    """Extract an explicit chronological ISO date range without guessing dates."""
    dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", message)
    if len(dates) != 2 or dates[0] > dates[1]:
        return None, None
    return dates[0], dates[1]


def _market_quote_summary(quote: dict[str, Any]) -> str:
    change = float(quote["change_percent"])
    direction = "up" if change > 0 else "down" if change < 0 else "unchanged"
    sign = "+" if change > 0 else ""
    return (
        f"{quote['bank_name']} is quoted at {quote['price']:,.2f} {quote['currency']}, "
        f"{direction} {sign}{change:.2f}% in the displayed session."
    )


def _market_comparison_summary(quotes: list[dict[str, Any]]) -> str:
    ranked = sorted(quotes, key=lambda quote: float(quote["price"]), reverse=True)
    highest = ranked[0]
    return (
        f"Among the {len(ranked)} requested banks, {highest['bank_name']} has the highest displayed share price "
        f"({highest['price']:,.2f} {highest['currency']}). Session changes are shown for every security."
    )


def _is_share_structure_question(message: str) -> bool:
    normalised = _normalise(message)
    return bool(
        re.search(r"capital\s+socia\w*", normalised)
        or re.search(r"capital.{0,60}(?:actions?|titres?|parts?)", normalised)
        or re.search(r"(?:nombre|nb|nbre|combien).{0,50}(?:actions?|actoin|titres?|parts?)", normalised)
        or re.search(r"(?:actions?|titres?)\s+en\s+circ", normalised)
        or "composition du capital" in normalised
        or re.search(r"\b(?:how many|number of)\s+(?:ordinary\s+)?shares?\b", normalised)
        or re.search(r"\bshares?\s+(?:made up|make up|comprising|in circulation|outstanding)\b", normalised)
        or re.search(r"\bshare capital.{0,80}\bshares?\b", normalised)
    )


def _share_structure_turn(message: str, context: ConversationContext, assessment: Any) -> dict[str, Any]:
    """Answer share-count questions from one annual-report excerpt, never Market Watch."""
    bank_id = assessment.detected_banks[0] if len(assessment.detected_banks) == 1 else None
    year = assessment.detected_years[0] if len(assessment.detected_years) == 1 else None
    next_context = _context(bank_id, year, mode="document")
    if bank_id is None:
        return {
            "type": "clarification", "mode": "document", "context": next_context.model_dump(),
            "missing_information": ["bank to analyse"],
            "message": "Please specify the bank whose share capital or number of shares you want to review.",
        }
    if year is None:
        return {
            "type": "clarification", "mode": "document", "context": next_context.model_dump(),
            "missing_information": ["reporting year or period"],
            "message": f"Which reporting year should I use for {bank_definitions()[bank_id][0]}'s share-capital composition? For example: 2025.",
        }
    evidence = retrieve_evidence(
        bank_id, year, "capital social nombre d'actions ordinaires en circulation valeur nominale", limit=4,
        include_neighbour_pages=True,
    )
    source = next((chunk for chunk in evidence if _share_count(chunk.text) is not None), None)
    if source is None:
        return {
            "type": "clarification", "mode": "document", "context": next_context.model_dump(),
            "missing_information": [],
            "message": "The available report does not identify the number of shares with enough certainty, so no value is inferred.",
        }
    shares = _share_count(source.text)
    assert shares is not None
    formatted_shares = f"{shares:,}"
    return {
        "type": "document", "mode": "document", "context": next_context.model_dump(),
        "answer": (
            f"As of 31 December {year}, {bank_definitions()[bank_id][0]} had {formatted_shares} ordinary shares in circulation. "
            f"This information comes from the official annual report, page {source.page_number}."
        ),
        "evidence": [source.model_dump()],
    }


def _share_count(text: str) -> int | None:
    patterns = (
        r"nombre d[’']actions ordinaires en circulation fin de (?:la )?p[ée]riode\s+([\d]{1,3}(?:\s[\d]{3})+)(?:\s{2,}|$)",
        r"nombre d[’']actions\s+([\d]{1,3}(?:\s[\d]{3})+)(?:\s{2,}|$)",
        r"capital social[\s,]*(?:de la banque )?(?:est )?(?:port[ée] .*?)?(?:divis[ée]|compos[ée]).{0,120}?([\d]{1,3}(?:\s[\d]{3})+)\s+actions",
        r"capital social.{0,180}?(?:divis[ée]|compos[ée]).{0,120}?([\d]{1,3}(?:\s[\d]{3})+)\s+actions",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            if digits:
                return int(digits)
    return None


def _display_official_name(value: str) -> str:
    """Present an uppercase PDF title as natural conversational prose."""
    lower_words = {"de", "des", "du", "et", "à", "au", "aux"}
    return " ".join(
        word.lower() if word.lower() in lower_words else word.capitalize()
        for word in value.split()
    )


def _normalise(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(character) != "Mn"
    ).replace("’", "'").replace("-", "-")


def _unknown_explicit_bank_references(message: str, metric_id: str | None) -> list[str]:
    """Find bank-like names explicitly supplied after a mapped financial metric.

    Only a constrained bank-list form is inspected.  This prevents an unknown
    name such as ``VCG`` from falling through to a previous conversation's
    BIAT/BT context, while ordinary prose remains outside this guard.
    """
    if metric_id is None:
        return []
    aliases = assessment_metrics().get(metric_id, [])
    normalised = _normalise(message)
    bank_phrase = ""
    for alias in sorted({_normalise(value) for value in aliases}, key=len, reverse=True):
        match = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalised)
        if match is None:
            continue
        suffix = normalised[match.end():]
        phrase = re.match(r"\s+(?:of|de|du|des)\s+(.+)", suffix)
        if phrase is not None:
            bank_phrase = phrase.group(1)
            break
    if not bank_phrase:
        return []
    bank_phrase = re.split(r"\b(?:in|en|for|pour)\s+20\d{2}\b", bank_phrase, maxsplit=1)[0]
    unresolved = bank_phrase
    known_aliases = {
        _normalise(alias)
        for _, (_, aliases_for_bank) in bank_definitions().items()
        for alias in aliases_for_bank
    }
    for alias in sorted(known_aliases, key=len, reverse=True):
        unresolved = re.sub(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", " ", unresolved)
    candidates = [
        token
        for token in re.findall(r"[a-z][a-z0-9']*", unresolved)
        if token not in _BANK_REFERENCE_STOPWORDS
    ]
    return list(dict.fromkeys(candidates))


def _display_unknown_bank_reference(value: str) -> str:
    """Keep common ticker-like unknown names readable in a clarification."""
    return value.upper() if len(value) <= 5 else value


def _profile_bank_id(message: str, *, bank_ids: list[str], year: int | None, metric_id: str | None) -> str | None:
    """Recognise a bank-profile request without enumerating question phrasings.

    The normalisation layer has already repaired the user's wording.  Here, a
    profile is simply a request that names one bank and contains no period,
    metric, or topical term.  Any remaining subject word routes to documentary
    retrieval instead of being forced into an identity answer.
    """
    if len(bank_ids) != 1 or year is not None or metric_id is not None:
        return None
    bank_id = bank_ids[0]
    remainder = _normalise(message)
    for alias in bank_definitions()[bank_id][1]:
        remainder = re.sub(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", " ", remainder)
    subject_words = [
        word for word in re.findall(r"[a-z]{2,}", remainder)
        if word not in _PROFILE_FILLER_WORDS
    ]
    return bank_id if not subject_words else None


def _is_plain_bank_selection(message: str, bank_id: str) -> bool:
    """Return true when the user supplied only a bank name to select it."""
    remainder = _normalise(message)
    for alias in bank_definitions()[bank_id][1]:
        remainder = re.sub(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", " ", remainder)
    return not re.search(r"[a-z0-9]", remainder)


def _is_explicit_documentary_request(message: str, assessment: Any) -> bool:
    """Recognise a named bank request for report content without relying on an LLM.

    This deliberately requires a report-content cue or a glossary concept. A
    bank name and a year alone remain ambiguous and do not open a report.
    """
    if len(assessment.detected_banks) != 1 or assessment.detected_metric:
        return False
    normalised = _normalise(message)
    return bool(_matching_document_concepts(message)) or any(cue in normalised for cue in _DOCUMENT_REQUEST_CUES)


def _is_explicit_identity_question(message: str) -> bool:
    """Distinguish “What is BIAT?” from “what about BIAT?” in a metric turn."""
    normalised = _normalise(message).strip(" ?!.")
    return bool(re.match(r"^(?:what|who)\s+is\s+", normalised))


def _context(bank_id: str | None, year: int | None, *, mode: str, topic: str | None = None, document_scope: str | None = None, document_anchor: str | None = None, document_anchor_page: int | None = None, document_query: str | None = None, document_search_status: str | None = None, metric_id: str | None = None, metric_bank_ids: list[str] | None = None, comparison_bank_ids: list[str] | None = None, comparison_metric_ids: list[str] | None = None) -> ConversationContext:
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
        document_query=document_query,
        document_search_status=document_search_status,
        metric_id=metric_id,
        metric_bank_ids=metric_bank_ids or [],
        comparison_bank_ids=comparison_bank_ids or [],
        comparison_metric_ids=comparison_metric_ids or [],
    )


def _document_clarification(context: ConversationContext) -> dict[str, Any]:
    missing: list[str] = []
    if not context.bank_id:
        missing.append("bank to analyse")
    if not context.reporting_year:
        missing.append("reporting year or period")
    return {
        "type": "clarification",
        "mode": "document",
        "context": context.model_dump(),
        "missing_information": missing,
        "message": "To continue this documentary analysis, please provide " + ("the bank and year" if len(missing) == 2 else "the missing detail") + ".",
    }


def _bank_identity_turn(bank_id: str, year: int | None, *, selection_only: bool = False) -> dict[str, Any]:
    """Answer bank identification from the title page of an official report."""
    bank_name = bank_definitions()[bank_id][0]
    if selection_only:
        answer = f"{bank_name} selected. Please specify the financial metric and reporting year you want to analyse."
        return {
            "type": "document",
            "mode": "document",
            "context": _context(bank_id, None, mode="document", topic="bank selection").model_dump(),
            "answer": answer,
            "analysis": {
                "intent": "bank_selection",
                "scope_label": "Selected bank",
                "scope_explanation": "A bank selection does not choose a report or financial year.",
                "direct_answer": answer,
                "findings": [],
            },
            "evidence": [],
        }
    available = reports_for([bank_id], [2021, 2022, 2023, 2024, 2025])
    source_year = year if any(report.year == year for report in available) else None
    source_year = source_year or max((report.year for report in available), default=None)
    if source_year is None:
        return {
            "type": "clarification",
            "mode": "document",
            "context": _context(bank_id, year, mode="document").model_dump(),
            "missing_information": [],
            "message": "No official report is available to identify this bank.",
        }

    evidence = retrieve_entity_evidence(bank_id, source_year, bank_definitions()[bank_id][0], limit=1)
    if not evidence:
        return {
            "type": "clarification",
            "mode": "document",
            "context": _context(bank_id, source_year, mode="document").model_dump(),
            "missing_information": [],
            "message": "The official report does not contain a sufficient identification excerpt.",
        }

    primary = evidence[0]
    title_line = next(
        (
            " ".join(line.split())
            for line in primary.text.splitlines()
            if len(" ".join(line.split())) > 4
            and not any(
                phrase in _normalise(line)
                for phrase in ("avis des societes", "etats financiers", "siege social", "publie ci-dessous")
            )
        ),
        bank_name,
    )
    answer = f"{bank_name} stands for {_display_official_name(title_line)}. [p. {primary.page_number}]"
    return {
        "type": "document",
        "mode": "document",
        "context": _context(bank_id, year, mode="document", topic="bank identification").model_dump(),
        "answer": answer,
        "analysis": {
            "intent": "bank_identification",
            "scope_label": "Official report identification",
            "scope_explanation": "This answer identifies the bank only; it does not assess its performance or outlook.",
            "direct_answer": answer,
            "findings": [],
        },
        "evidence": [primary.model_dump()],
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


def _document_content_terms(message: str) -> set[str]:
    """Separate a substantive reformulation from a conversational follow-up."""
    return {
        term
        for term in re.findall(r"[a-z]{4,}", _normalise(message))
        if term not in _DOCUMENT_FOLLOWUP_FILLERS
    }


def _matching_document_concepts(message: str) -> list[dict[str, object]]:
    """Return the most specific bilingual concepts present in a message."""
    normalized_message = _normalise(message)
    matches: list[dict[str, object]] = []
    for concept in documentary_glossary():
        raw_aliases = concept.get("aliases", [])
        aliases = (
            [str(alias) for aliases_by_language in raw_aliases.values() for alias in aliases_by_language]
            if isinstance(raw_aliases, dict)
            else [str(alias) for alias in raw_aliases]
        )
        if any(re.search(rf"\b{re.escape(_normalise(alias))}\b", normalized_message) for alias in aliases):
            matches.append(concept)
    if not matches:
        return []
    highest_priority = max(int(item.get("priority", 0)) for item in matches)
    return [item for item in matches if int(item.get("priority", 0)) == highest_priority]


def _document_query_expansion(message: str) -> str:
    """Add official terminology for the most specific recognised concept.

    The mapping is declarative data, not an answer: it only broadens retrieval
    to the wording actually used in a report.  The returned answer still needs
    a source excerpt selected from that report.
    """
    terms: list[str] = []
    for concept in _matching_document_concepts(message):
        terms.extend(str(term) for term in concept.get("search_terms", []))
    return " ".join(dict.fromkeys(terms))


def _document_turn(message: str, context: ConversationContext, bank_id: str | None, year: int | None, *, continuation: bool, expand_scope: bool, document_scope: str | None) -> dict[str, Any]:
    content_terms = _document_content_terms(message)
    previous_failed_search = continuation and context.document_search_status == "no_evidence"
    refined_after_failure = previous_failed_search and bool(content_terms)
    current_concepts = {str(item["concept_id"]) for item in _matching_document_concepts(message)}
    previous_concepts = {str(item["concept_id"]) for item in _matching_document_concepts(context.topic or "")}
    refined_concept = bool(current_concepts and current_concepts != previous_concepts)
    topic = _topic(message) if refined_after_failure or refined_concept or not (continuation and context.topic) else context.topic
    updated = _context(
        bank_id,
        year,
        mode="document",
        topic=topic,
        document_scope=document_scope,
        document_anchor=context.document_anchor,
        document_anchor_page=context.document_anchor_page,
        document_query=topic,
        document_search_status=context.document_search_status if continuation else None,
    )
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

    if previous_failed_search and not content_terms:
        previous_query = context.document_query or context.topic or "the previous request"
        return {
            "type": "clarification",
            "mode": "document",
            "context": updated.model_dump(),
            "missing_information": [],
            "message": (
                f"I cannot verify a relevant passage for “{previous_query}” in the {updated.bank_name} "
                f"{updated.reporting_year} report, so I do not want to guess. Please name the portfolio category, "
                "note, balance-sheet line or investment type you mean."
            ),
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

    suffix = f"de {updated.bank_name} en {updated.reporting_year}"
    if continuation and topic:
        suffix += f" about {topic}"
    # A follow-up such as “in 2025” supplies a period but no subject.  Expand
    # from the retained topic as well, so the bilingual concept is not lost
    # between turns.
    bridge_terms = _document_query_expansion(f"{message} {topic}")
    search_query = f"{message.strip()} {suffix} {bridge_terms}".strip()
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
        bank_name = updated.bank_name or updated.bank_id
        return {
            "type": "clarification",
            "mode": "document",
            "context": updated.model_copy(update={"document_search_status": "no_evidence"}).model_dump(),
            "missing_information": [],
            "message": (
                f"I found the {bank_name} {updated.reporting_year} official report, but no sufficiently "
                f"relevant source passage for “{topic}”. Rephrase the requested detail or name the note, "
                "risk, accounting policy or financial statement you want to examine."
            ),
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
        "context": updated.model_copy(update={"document_search_status": "found"}).model_dump(),
        # `answer` remains for clients already connected to the API. New clients
        # render `analysis`, whose fields make the reasoning and its boundaries clear.
        "answer": analysis["direct_answer"],
        "analysis": analysis,
        "evidence": [chunk.model_dump() for chunk in evidence],
    }


def _metric_context(context: ConversationContext, bank_id: str | None, year: int | None, metric_id: str | None) -> ConversationContext:
    """Keep the two most recent banks only while the same metric is active."""
    recent_bank_ids: list[str] = []
    if context.mode == "metric" and context.metric_id == metric_id:
        recent_bank_ids.extend(context.metric_bank_ids)
        if context.bank_id:
            recent_bank_ids.append(context.bank_id)
    if bank_id:
        recent_bank_ids.append(bank_id)
    recent_bank_ids = list(dict.fromkeys(recent_bank_ids))[-2:]
    return _context(bank_id, year, mode="metric", metric_id=metric_id, metric_bank_ids=recent_bank_ids)


def _metric_turn(message: str, context: ConversationContext, bank_id: str | None, year: int | None, metric_id: str | None) -> dict[str, Any]:
    if bank_id is None:
        bank_id = context.bank_id
    if year is None:
        year = context.reporting_year
    metric_context = _metric_context(context, bank_id, year, metric_id)
    if not bank_id or not year or not metric_id:
        missing_information: list[str] = []
        if not bank_id:
            missing_information.append("bank to analyse")
        if not year:
            missing_information.append("reporting year or period")
        if not metric_id:
            missing_information.append("financial metric to analyse")
        if bank_id and metric_id and not year:
            metric_label = metric_id.replace("_", " ")
            message_text = (
                f"Which reporting year should I use for {bank_definitions()[bank_id][0]}'s {metric_label}? "
                "For example: 2023, 2024 or 2025."
            )
        else:
            message_text = "Please specify the missing bank, reporting year or financial metric."
        return {
            "type": "clarification",
            "mode": "metric",
            "context": metric_context.model_dump(),
            "missing_information": missing_information,
            "message": message_text,
        }
    if not reports_for([bank_id], [year]):
        return {
            "type": "clarification",
            "mode": "metric",
            "context": metric_context.model_dump(),
            "missing_information": [],
            "message": "The corresponding official report is not yet available in the corpus.",
        }
    fact = auto_validated_fact(bank_id, year, metric_id)
    if fact is None:
        source_fact = source_matched_fact(bank_id, year, metric_id)
        if source_fact is not None:
            unit = "thousand TND" if source_fact.unit_scale == "thousand" else source_fact.currency
            return {
                "type": "source_value",
                "mode": "metric",
                "context": metric_context.model_dump(),
                "metric_id": metric_id,
                "value": source_fact.value,
                "currency": source_fact.currency,
                "unit_scale": source_fact.unit_scale,
                "reporting_year": source_fact.reporting_year,
                "source_document": source_fact.source_path,
                "page_number": source_fact.page_number,
                "source_excerpt": source_fact.source_excerpt,
                "source_label": source_fact.raw_label,
                "answer": (
                    f"{bank_definitions()[bank_id][0]} reports {source_fact.value} {unit} "
                    f"as {source_fact.raw_label} in {year}. [p. {source_fact.page_number}]"
                ),
            }
        return {
            "type": "clarification",
            "mode": "metric",
            "context": metric_context.model_dump(),
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
        "context": metric_context.model_dump(),
        **answer.model_dump(mode="json"),
    }


def _comparable_fact(bank_id: str, year: int, metric_id: str):
    """Return a value safe to place beside another official-report value.

    Automatic validation remains preferred. Metrics such as demand deposits
    live in a note rather than the validation core, so a uniquely matched,
    bank-specific source row is also comparable when every bank has one.
    """
    return auto_validated_fact(bank_id, year, metric_id) or source_matched_fact(bank_id, year, metric_id)


def _metric_interpretation_turn(context: ConversationContext) -> dict[str, Any]:
    """Put one metric in its available year-on-year context without a normality claim."""
    bank_id = context.bank_id
    year = context.reporting_year
    metric_id = context.metric_id
    assert bank_id is not None and year is not None and metric_id is not None
    current = _comparable_fact(bank_id, year, metric_id)
    previous = _comparable_fact(bank_id, year - 1, metric_id)
    bank_name = bank_definitions()[bank_id][0]
    if current is None or previous is None:
        answer = (
            f"A single reported {metric_id.replace('_', ' ')} value is not enough to judge whether it is normal. "
            "A prior-year or peer comparison is needed."
        )
    else:
        variation = current.value - previous.value
        percentage = (variation / previous.value * 100) if previous.value else None
        unit = "thousand TND" if current.unit_scale == "thousand" else current.currency
        percentage_text = f" ({percentage.quantize(Decimal('0.1'))}%)" if percentage is not None else ""
        direction = "increased" if variation >= 0 else "decreased"
        answer = (
            f"Compared with {year - 1}, {bank_name}'s {metric_id.replace('_', ' ')} {direction} by "
            f"{abs(variation):,.0f} {unit}{percentage_text}, reaching {current.value:,.0f} {unit} in {year}. "
            "This establishes the year-on-year change, but it is not enough on its own to conclude whether the result is normal; "
            "a peer comparison or a longer trend is needed."
        )
    return {
        "type": "metric_analysis",
        "mode": "metric",
        "context": context.model_dump(),
        "metric_id": metric_id,
        "reporting_year": year,
        "answer": answer,
    }


def _comparison_metric_history(
    context: ConversationContext, bank_ids: list[str], year: int | None, metric_id: str | None
) -> list[str]:
    """Keep a bounded metric history only inside one stable comparison scope."""
    if metric_id is None:
        return list(context.comparison_metric_ids)
    same_comparison = (
        context.mode == "comparison"
        and context.reporting_year == year
        and context.comparison_bank_ids == bank_ids
    )
    existing = context.comparison_metric_ids if same_comparison else []
    return [*([item for item in existing if item != metric_id]), metric_id][-5:]


def _comparison_turn(context: ConversationContext, bank_ids: list[str], year: int | None, metric_id: str | None) -> dict[str, Any]:
    """Compare one traceable reported metric across the banks named by the user."""
    metric_history = _comparison_metric_history(context, bank_ids, year, metric_id)
    if year is None or metric_id is None:
        missing = [item for item, value in [("reporting year or period", year), ("financial metric to analyse", metric_id)] if value is None]
        return {
            "type": "clarification",
            "mode": "comparison",
            "context": _context(None, year, mode="comparison", metric_id=metric_id, comparison_bank_ids=bank_ids, comparison_metric_ids=metric_history).model_dump(),
            "missing_information": missing,
            "message": "To compare banks reliably, please provide the year and the financial metric to compare.",
        }

    values: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for bank_id in bank_ids:
        if not reports_for([bank_id], [year]):
            unavailable.append(bank_definitions()[bank_id][0])
            continue
        fact = _comparable_fact(bank_id, year, metric_id)
        if fact is None:
            unavailable.append(bank_definitions()[bank_id][0])
            continue
        values.append({"bank_id": bank_id, "bank_name": bank_definitions()[bank_id][0], **fact.model_dump(mode="json")})
    if unavailable:
        names = ", ".join(unavailable)
        return {
            "type": "clarification",
            "mode": "comparison",
            "context": _context(None, year, mode="comparison", metric_id=metric_id, comparison_bank_ids=bank_ids, comparison_metric_ids=metric_history).model_dump(),
            "missing_information": [],
            "message": f"I cannot compare this metric because no uniquely matched official-report value is available for {names} in {year}.",
        }

    return {
        "type": "comparison",
        "mode": "comparison",
        "context": _context(None, year, mode="comparison", metric_id=metric_id, comparison_bank_ids=bank_ids, comparison_metric_ids=metric_history).model_dump(),
        "metric_id": metric_id,
        "reporting_year": year,
        "values": values,
    }


def _comparison_analysis_turn(message: str, context: ConversationContext) -> dict[str, Any]:
    """Explain an active comparison from evidence in each selected report."""
    bank_ids = context.comparison_bank_ids
    year = context.reporting_year
    metric_id = context.metric_id
    if len(bank_ids) < 2 or year is None or metric_id is None:
        return {
            "type": "clarification",
            "mode": "comparison",
            "context": context.model_dump(),
                "missing_information": ["active comparison"],
            "message": "Please name the banks, year and metric you want to compare.",
        }

    values: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for bank_id in bank_ids:
        fact = _comparable_fact(bank_id, year, metric_id)
        if fact is None:
            unavailable.append(bank_definitions()[bank_id][0])
            continue
        values.append({"bank_id": bank_id, "bank_name": bank_definitions()[bank_id][0], **fact.model_dump(mode="json")})
    if unavailable:
        return {
            "type": "clarification",
            "mode": "comparison",
            "context": context.model_dump(),
            "missing_information": [],
            "message": f"I cannot analyse this comparison because no uniquely matched official-report value is available for {', '.join(unavailable)} in {year}.",
        }

    metric_terms = " ".join(assessment_metrics().get(metric_id, [metric_id.replace("_", " ")]))
    evidence: list[Any] = []
    seen_chunks: set[str] = set()
    for bank_id in bank_ids:
        query = f"{metric_terms} composition evolution explanation"
        for chunk in retrieve_evidence(bank_id, year, query, limit=2, include_neighbour_pages=True):
            if chunk.chunk_id not in seen_chunks:
                evidence.append(chunk)
                seen_chunks.add(chunk.chunk_id)
    if not evidence:
        return {
            "type": "clarification",
            "mode": "comparison",
            "context": context.model_dump(),
            "missing_information": [],
            "message": "The reported values can be compared, but the available report excerpts do not provide enough evidence to explain the difference.",
        }

    bank_names = ", ".join(bank_definitions()[bank_id][0] for bank_id in bank_ids)
    analysis_question = (
        f"The user asks: {message}\n\n"
        f"Compare the reported {metric_id.replace('_', ' ')} for {bank_names} in {year}. "
        "Do not call the difference normal or abnormal. Explain only factors stated in the supplied excerpts; "
        "if they do not explain the difference, say so clearly."
    )
    source_synthesis = answer_from_evidence(analysis_question, evidence)
    # The documentary fallback intentionally exposes raw excerpts. That is
    # useful for a document question, but unreadable as the lead paragraph of
    # a comparison: the values are already displayed as cards and the excerpts
    # remain available on demand below. Keep only a validated prose synthesis.
    if source_synthesis.startswith("Answer based directly on the most relevant report excerpts:"):
        source_synthesis = ""
    answer = _comparison_gap_summary(values, source_synthesis, metric_id=metric_id)
    return {
        "type": "comparison_analysis",
        "mode": "comparison",
        "context": context.model_dump(),
        "metric_id": metric_id,
        "reporting_year": year,
        "values": values,
        "answer": answer,
        "evidence": [chunk.model_dump() for chunk in evidence],
        "analysis": {
            "scope_label": "Comparative analysis of official report excerpts",
            "scope_explanation": "This analysis explains only factors evidenced in the selected official-report excerpts; it does not use market data or make a normality judgment.",
        },
    }


def _multi_metric_comparison_analysis_turn(context: ConversationContext) -> dict[str, Any]:
    """Build a comparable dashboard for the metrics retained in this dossier."""
    bank_ids = context.comparison_bank_ids
    year = context.reporting_year
    metric_ids = context.comparison_metric_ids
    if len(bank_ids) < 2 or year is None or len(metric_ids) < 2:
        return {
            "type": "clarification",
            "mode": "comparison",
            "context": context.model_dump(),
            "missing_information": ["at least two compared metrics"],
            "message": "Please compare at least two metrics in the same bank set and year first.",
        }

    metrics: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for metric_id in metric_ids:
        values: list[dict[str, Any]] = []
        for bank_id in bank_ids:
            fact = _comparable_fact(bank_id, year, metric_id)
            if fact is None:
                unavailable.append(f"{metric_id} for {bank_definitions()[bank_id][0]}")
                continue
            values.append({"bank_id": bank_id, "bank_name": bank_definitions()[bank_id][0], **fact.model_dump(mode="json")})
        if len(values) == len(bank_ids):
            metrics.append({"metric_id": metric_id, "reporting_year": year, "values": values})

    if unavailable:
        return {
            "type": "clarification",
            "mode": "comparison",
            "context": context.model_dump(),
            "missing_information": [],
            "message": "A multi-metric comparison needs a uniquely matched value for every selected bank. Missing: " + ", ".join(unavailable) + ".",
        }

    labels = ", ".join(metric_id.replace("_", " ") for metric_id in metric_ids)
    return {
        "type": "multi_metric_comparison_analysis",
        "mode": "comparison",
        "context": context.model_dump(),
        "reporting_year": year,
        "metrics": metrics,
        "answer": (
            f"This comparative dashboard covers {labels} across {len(bank_ids)} banks in {year}. "
            "It compares reported values and rankings only; the available statements do not by themselves establish causal explanations for the gaps."
        ),
        "analysis": {
            "scope_label": "Multi-metric comparative analysis",
            "scope_explanation": "Each chart uses the official reported values for one metric. Scales differ by metric and are not comparable across charts.",
        },
    }


def _comparison_gap_summary(
    values: list[dict[str, Any]], source_synthesis: str = "", *, metric_id: str = "demand_deposits"
) -> str:
    """Give a clean reading that preserves the full comparison scope."""
    numeric_values: list[tuple[Decimal, str]] = []
    for item in values:
        try:
            numeric_values.append((Decimal(str(item["value"])), str(item["bank_name"])))
        except (KeyError, InvalidOperation):
            continue
    if len(numeric_values) < 2:
        return source_synthesis or "The reported values are available above."

    smallest, largest = min(numeric_values), max(numeric_values)
    difference = largest[0] - smallest[0]
    ratio = largest[0] / smallest[0] if smallest[0] else None
    ratio_text = f"about {ratio.quantize(Decimal('0.1'))}×" if ratio is not None else "materially"
    metric_label = metric_id.replace("_", " ")
    caveat = (
        "The selected excerpts establish the reported differences, but do not attribute them to a documented cause. "
        "They are therefore not enough to say whether the gaps are normal or to explain them conclusively."
    )
    if len(numeric_values) == 2:
        summary = (
            f"{largest[1]} reported {difference:,.0f} thousand TND more in {metric_label} than "
            f"{smallest[1]} in {values[0]['reporting_year']} — {ratio_text} the smaller balance. {caveat}"
        )
    else:
        ranked = sorted(numeric_values, reverse=True)
        ranking = "; ".join(f"{name} ({value:,.0f})" for value, name in ranked)
        second_value, second_name = ranked[1]
        summary = (
            f"The reported ranking for {metric_label} in {values[0]['reporting_year']} is: {ranking}. "
            f"{largest[1]} leads {second_name} by {largest[0] - second_value:,.0f} thousand TND; "
            f"the full range from {largest[1]} to {smallest[1]} is {difference:,.0f} thousand TND ({ratio_text}). "
            f"{caveat}"
        )
    return f"{summary}\n\n{source_synthesis}" if source_synthesis else summary


def answer_conversation_turn(
    message: str,
    context: ConversationContext,
    *,
    routing_message: str | None = None,
) -> dict[str, Any]:
    """Execute one plan while keeping language cleanup separate from intent.

    ``message`` is the locally normalised text used for deterministic reference
    extraction. ``routing_message`` is the untouched user wording used by the
    semantic planner, so a rewrite can never narrow an intent such as “all
    banks” before scope is decided.
    """
    assessment = assess_request(message)
    safety_response = _safety_clarification(message, context, assessment)
    if safety_response is not None:
        return safety_response
    unknown_bank_references = _unknown_explicit_bank_references(message, assessment.detected_metric)
    if unknown_bank_references:
        labels = ", ".join(f"“{_display_unknown_bank_reference(value)}”" for value in unknown_bank_references)
        supported = ", ".join(name for name, _ in bank_definitions().values())
        return {
            "type": "clarification",
            "mode": "idle",
            "context": ConversationContext().model_dump(),
            "missing_information": ["supported bank name"],
            "message": (
                f"I do not recognise {labels} as a supported bank. Please provide its full name or choose from: {supported}."
            ),
        }
    # A fully specified two-bank metric question is a legitimate comparison.
    # Do not send it to a language-model planner that might ask for a bank that
    # was already supplied by the user.
    if (
        len(assessment.detected_banks) >= 2
        and len(assessment.detected_years) == 1
        and assessment.detected_metric is not None
    ):
        return _comparison_turn(
            context,
            assessment.detected_banks,
            assessment.detected_years[0],
            assessment.detected_metric,
        )
    if assessment.decision == "abstain":
        return {
            "type": "clarification",
            "mode": context.mode,
            "context": context.model_dump(),
            "missing_information": [],
            "message": "The official report for the requested year is not available in the corpus, so I cannot provide a verified value.",
        }
    if (
        assessment.detected_banks
        and assessment.detected_years
        and assessment.detected_metric is None
        and context.metric_id is None
        and _OUT_OF_SCOPE_METRIC_CUES.search(_normalise(message))
    ):
        return {
            "type": "clarification",
            "mode": context.mode,
            "context": context.model_dump(),
            "missing_information": assessment.missing_information,
            "message": assessment.reason,
        }
    if (
        len(assessment.detected_banks) == 1
        and len(assessment.detected_years) == 1
        and assessment.detected_metric is None
        and context.metric_id is None
        and context.mode != "document"
        and _FINANCIAL_STATEMENT_ACCESS_CUES.search(_normalise(message))
        and not _is_explicit_current_quote_request(routing_message or message)
        and not _is_explicit_documentary_request(message, assessment)
    ):
        bank_id = assessment.detected_banks[0]
        year = assessment.detected_years[0]
        metric_context = _context(bank_id, year, mode="metric")
        return {
            "type": "clarification",
            "mode": "metric",
            "context": metric_context.model_dump(),
            "missing_information": ["financial metric to analyse"],
            "message": (
                f"Please specify the financial metric to analyse for {bank_definitions()[bank_id][0]} in {year}, "
                "for example net banking income, net income or customer deposits."
            ),
        }
    if _is_share_structure_question(message):
        return _share_structure_turn(message, context, assessment)
    # Several named banks alone do not establish a financial comparison.  Keep
    # them as a pending Market Watch selection so an immediately following
    # “current share prices” can compare the exact list the user supplied.
    if (
        len(assessment.detected_banks) >= 2
        and assessment.detected_metric is None
        and context.metric_id is None
        and context.mode != "market"
        and _requests_bank_comparison(routing_message or message)
    ):
        pending_market_context = ConversationContext(
            mode="market",
            market_bank_ids=assessment.detected_banks,
            topic="market_data",
        )
        return {
            "type": "clarification",
            "mode": "market",
            "context": pending_market_context.model_dump(),
            "missing_information": ["comparison criterion"],
            "message": (
                "Please specify what you want to compare: current share prices, "
                "a financial metric such as net banking income, net income or deposits, "
                "and the reporting year where applicable."
            ),
        }
    # Preserve scope words from the user's original wording.  Normalisation is
    # used for safe bank/year/metric extraction, but it must never turn “all
    # banks” into “all bank” before the conversation state machine sees it.
    plan = _turn_plan(message, context, assessment, routing_message)
    if (
        context.mode == "document"
        and context.document_search_status == "no_evidence"
        and assessment.detected_metric is None
        and not _document_content_terms(message)
    ):
        # A short confirmation after a documented retrieval failure has no new
        # subject to route elsewhere.  Keep it in the failed dossier so the
        # response can state the verification limit instead of replaying it.
        return _document_turn(
            message,
            context,
            context.bank_id,
            context.reporting_year,
            continuation=True,
            expand_scope=False,
            document_scope=context.document_scope,
        )
    operation = plan["operation"]
    bank_ids = _plan_banks(plan, context, assessment)
    year = _plan_year(plan, context, assessment)
    metric_id = _plan_metric(plan, context, assessment)

    if operation == "metric_lookup":
        if len(bank_ids) >= 2:
            return _comparison_turn(context, bank_ids, year, metric_id)
        if not bank_ids and len(context.metric_bank_ids) >= 2:
            return {
                "type": "clarification",
                "mode": "metric",
                "context": context.model_dump(),
                "missing_information": ["bank or comparison scope"],
                "message": "The active metric involves two banks. Please name one bank or ask for a comparison.",
            }
        return _metric_turn(message, context, bank_ids[0] if bank_ids else None, year, metric_id)
    if operation == "compare":
        return _comparison_turn(context, bank_ids, year, metric_id)
    if operation == "comparison_analysis":
        return _comparison_analysis_turn(message, context)
    if operation == "multi_metric_analysis":
        return _multi_metric_comparison_analysis_turn(context)
    if operation == "metric_interpretation":
        if _has_single_metric_context(context):
            return _metric_interpretation_turn(context)
        return {
            "type": "clarification",
            "mode": "metric",
            "context": context.model_dump(),
            "missing_information": ["active result"],
            "message": "Please select one reported value before asking for an interpretation.",
        }
    if operation == "general_education":
        return _general_education_turn(message, context)
    if operation == "market":
        start_date, end_date = _market_date_range(routing_message or message)
        market_request = _classify_market_request(message, context) or "current_quote"
        # A current quote belongs to the live market session, never to the
        # accounting year retained by a preceding documentary conversation.
        market_year = None if market_request == "current_quote" else year
        return _market_turn(
            context, bank_ids, market_year, market_request,
            start_date=start_date, end_date=end_date,
        )
    if operation == "bank_profile":
        if len(bank_ids) == 1:
            return _bank_identity_turn(
                bank_ids[0],
                year,
                selection_only=_is_plain_bank_selection(message, bank_ids[0]),
            )
        return {
            "type": "clarification",
            "mode": "document",
            "context": context.model_dump(),
            "missing_information": ["bank to analyse"],
            "message": "Please name the bank you want to identify.",
        }
    if operation == "documentary":
        bank_id = bank_ids[0] if len(bank_ids) == 1 else None
        return _document_turn(
            message,
            context,
            bank_id,
            year,
            continuation=plan["document_action"] != "new",
            expand_scope=plan["document_action"] == "expand_scope",
            document_scope=None if plan["document_scope"] == "none" else plan["document_scope"],
        )
    return {
        "type": "clarification",
        "mode": context.mode,
        "context": context.model_dump(),
        "missing_information": [],
        "message": plan["clarification"] or "Could you clarify what you would like to understand?",
    }
