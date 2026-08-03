"""Grounded, source-preserving document analysis with an optional LLM."""

from __future__ import annotations

import json
import re
import unicodedata

from myfinance_contracts import EvidenceChunk

from myfinance_orchestrator.model_provider import USE_LLM, complete

MODEL_EXCERPT_CHARS = 900
_REFORMULATION_WORDS = {
    "banque", "biat", "passage", "note", "rapport", "indique", "precise", "decrit",
    "explique", "presente", "mentionne", "souligne", "montre", "regroupe", "rassemble",
    "comprend", "concerne", "ce", "cette", "ces",
    "dans", "pour", "avec", "sans", "entre", "ainsi", "dont", "elle", "il", "les",
    "des", "une", "afin", "reste", "sont", "etre",
}


def _normalise(value: str) -> str:
    normalised = "".join(
        character
        for character in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(character) != "Mn"
    )
    return normalised.replace("’", "'").replace("‘", "'")


def _relevant_excerpt(text: str, question: str, limit: int) -> str:
    """Center an excerpt on the requested subject instead of a page header."""
    compact = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if len(compact) <= limit:
        return compact
    normalized_text = _normalise(compact)
    terms = [term for term in re.findall(r"[a-z]{4,}", _normalise(question)) if term not in {"biat", "explique", "comment", "quoi", "quel", "quelle"}]
    start = 0
    if len(terms) >= 2:
        phrase = re.search(rf"{re.escape(terms[0])}.{{0,80}}{re.escape(terms[1])}", normalized_text)
        if phrase:
            start = phrase.start()
    if start == 0:
        positions = [normalized_text.find(term) for term in terms if normalized_text.find(term) >= 0]
        if positions:
            start = min(positions)
    note_start = normalized_text.rfind("note", max(0, start - 80), start + 1)
    if note_start >= 0:
        start = note_start
    excerpt = compact[start:start + limit]
    return excerpt.rsplit(" ", 1)[0] + "…" if start + limit < len(compact) else excerpt


def _shorten_for_model(text: str, question: str) -> str:
    """Keep the model input well inside the local model's context window."""
    return _relevant_excerpt(text, question, MODEL_EXCERPT_CHARS)


def _extractive_answer(question: str, evidence: list[EvidenceChunk]) -> str:
    """Give a useful, non-inferential fallback when the local model ignores citations."""
    excerpts: list[str] = []
    for chunk in evidence:
        excerpt = _relevant_excerpt(chunk.text, question, 620)
        excerpts.append(f"- « {excerpt} » [p. {chunk.page_number}]")
    return "Réponse fondée directement sur les passages les plus pertinents du rapport :\n\n" + "\n\n".join(excerpts)


def _safe_qualitative_analysis(answer: str, evidence: list[EvidenceChunk]) -> str:
    """Keep only cited, qualitative sentences from a local-model synthesis.

    A local model can correctly explain a mechanism and then append an unsupported
    figure or a speculative detail.  We do not discard the useful explanation: each
    cited segment is checked independently, and a segment containing a number beyond
    its page citation is removed.
    """
    allowed_pages = {chunk.page_number for chunk in evidence}
    citation = re.compile(r"\[p\.\s*(\d+)\]", re.IGNORECASE)
    segments = re.findall(r"(?s).*?\[p\.\s*\d+\]", answer)
    accepted: list[str] = []
    for segment in segments:
        pages = [int(page) for page in citation.findall(segment)]
        without_citations = citation.sub("", segment)
        if not pages or not set(pages).issubset(allowed_pages):
            continue
        if re.search(r"\d", without_citations):
            continue
        if len(re.sub(r"\s+", "", without_citations)) < 20:
            continue
        accepted.append(" ".join(segment.split()))
    return " ".join(accepted)


def _terms(value: str) -> set[str]:
    """Return conservative stems for a claim-to-evidence lexical check."""
    return {
        word[:-1] if len(word) > 5 and word.endswith(("s", "x")) else word
        for word in re.findall(r"[a-z]{4,}", _normalise(value))
    }


def _extract_json_object(value: str) -> dict[str, object] | None:
    """Accept a JSON object only; fenced prose is not a valid model response."""
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _claim_is_supported(summary: str, quote: str, page: int, evidence: list[EvidenceChunk]) -> bool:
    """Require an exact PDF quote and conservative wording for every model claim.

    This is deliberately stricter than page-level citation.  A model may use a
    short, reader-friendly sentence, but its meaningful words must come from the
    exact quote it supplied, and that quote must occur on the cited source page.
    """
    if re.search(r"\d", summary) or len(quote.split()) < 6:
        return False
    normalized_quote = " ".join(_normalise(quote).split())
    source_texts = [" ".join(_normalise(chunk.text).split()) for chunk in evidence if chunk.page_number == page]
    if not normalized_quote or not any(normalized_quote in text for text in source_texts):
        return False
    summary_terms = _terms(summary)
    quote_terms = _terms(quote)
    unsupported_terms = summary_terms - quote_terms - _REFORMULATION_WORDS
    anchored_terms = summary_terms & quote_terms
    return len(anchored_terms) >= 2 and not unsupported_terms


def _validated_claim_synthesis(model_response: str, evidence: list[EvidenceChunk]) -> str:
    """Return only model claims that have an exact, page-level proof in the PDF."""
    payload = _extract_json_object(model_response)
    if payload is None or not isinstance(payload.get("claims"), list):
        return ""
    accepted: list[str] = []
    for claim in payload["claims"][:2]:
        if not isinstance(claim, dict):
            continue
        summary = claim.get("summary")
        quote = claim.get("evidence_quote")
        page = claim.get("page")
        if not isinstance(summary, str) or not isinstance(quote, str) or not isinstance(page, int):
            continue
        compact_summary = " ".join(summary.split()).strip()
        if _claim_is_supported(compact_summary, quote, page, evidence):
            accepted.append(f"{compact_summary} [p. {page}]")
    return " ".join(accepted)


def _source_reading(question: str, evidence: list[EvidenceChunk]) -> str:
    """Provide a useful analytical reading when local generation is unavailable.

    This is deliberately narrower than a language-model answer: it explains the
    accounting role visible in the selected note and never introduces a number.
    """
    primary = evidence[0]
    text = _normalise(primary.text)
    question_text = _normalise(question)
    page = primary.page_number

    if ("autre" in question_text or "y a" in question_text or "existe" in question_text) and ("transaction" in question_text or "parties liees" in question_text):
        conclusion = next(
            (
                chunk
                for chunk in evidence
                if "n'ont pas revele" in " ".join(_normalise(chunk.text).split())
                and "autres conventions" in " ".join(_normalise(chunk.text).split())
            ),
            None,
        )
        listed_pages = sorted({chunk.page_number for chunk in evidence if chunk is not conclusion})
        citations = " ".join(f"[p. {item}]" for item in listed_pages[:3])
        if conclusion:
            return (
                "Oui. La recherche élargie dans le rapport spécial fait apparaître plusieurs conventions ou opérations "
                f"au-delà du premier extrait consulté. {citations} Les commissaires indiquent qu’en dehors des conventions "
                f"et opérations présentées, leur revue n’a pas révélé d’autres opérations dans le périmètre légal examiné. [p. {conclusion.page_number}]"
            )
        return f"La recherche élargie a identifié plusieurs conventions ou opérations au-delà de la première note consultée. {citations}"

    if "parties liees" in text or "parties liees" in question_text:
        entity = "GSM" if "gsm" in text else "l’entité liée mentionnée dans la note"
        activity = " autour de la location d’un parcours de golf" if "parcours" in text and "golf" in text else ""
        return (
            "Cette note isole les opérations avec des entités liées afin d’en rendre la nature et les "
            f"conditions transparentes. Dans le cas décrit, {primary.bank_name} documente une relation avec {entity}{activity}. "
            f"[p. {page}]"
        )

    if "portefeuille d'encaissement" in text or "portefeuille d'encaissement" in question_text:
        return (
            "Le portefeuille d’encaissement regroupe des valeurs reçues pour le compte de tiers et encore "
            "en attente d’encaissement. La note précise qu’elles sont suivies séparément et ne sont pas "
            f"présentées au bilan. [p. {page}]"
        )

    if "etat de flux de tresorerie" in text or "etat de flux de tresorerie" in question_text:
        return (
            "La note explique l’effet des variations de change sur les liquidités de la banque, puis décrit "
            "les principales composantes de sa trésorerie et de ses équivalents de liquidités. "
            f"[p. {page}]"
        )

    if "risque de contrepartie" in text or "risques de credit" in question_text:
        return (
            "Le passage relie le risque de crédit à la capacité des contreparties à honorer leurs engagements. "
            f"{primary.bank_name} présente les mécanismes de couverture et le suivi des créances selon leur niveau de risque. "
            f"[p. {page}]"
        )

    title = re.search(r"(?:note\s+[ivxlcdm0-9]+\s*[–-]\s*)([^\n]+)", primary.text, re.IGNORECASE)
    subject = title.group(1).strip() if title else "ce sujet"
    return (
        f"Le rapport traite « {subject} » dans une note dédiée. Cette présentation permet de distinguer "
        f"le mécanisme concerné des principaux tableaux financiers et d’en consulter les conditions dans la source. [p. {page}]"
    )


def answer_from_evidence(question: str, evidence: list[EvidenceChunk]) -> str:
    """Synthesize only claims that pass exact quote and page validation."""
    # The extractive response is source-locked and immediate. Generation is
    # opt-in so either a local model or a cloud provider can be unavailable
    # without weakening the answer.
    if not USE_LLM:
        return _extractive_answer(question, evidence)
    context = "\n\n".join(
        f"[PAGE {chunk.page_number}]\n{_shorten_for_model(chunk.text, question)}" for chunk in evidence
    )
    prompt = f"""Tu es l'analyste documentaire de MyFinance. Tu dois produire une
reformulation strictement prouvable par le passage officiel fourni.

Réponds uniquement avec un objet JSON valide, sans balise Markdown :
{{"claims":[{{"summary":"reformulation courte sans chiffre", "evidence_quote":"copie exacte d'au moins six mots du passage", "page":12}}]}}

Règles impératives :
- Produis une ou deux claims maximum.
- `evidence_quote` doit être une copie exacte et continue du passage sur la page indiquée.
- `summary` peut reformuler, mais ne doit ajouter aucune idée, chiffre, date, taux, appréciation ou définition externe.
- Ne cite jamais une page absente du passage fourni.
- Si le passage ne permet pas une reformulation sûre, réponds exactement : {{"claims":[]}}.

Question : {question}

Passage officiel :
{context}
"""
    model_response = complete(prompt, json_mode=True, max_tokens=320)
    synthesis = _validated_claim_synthesis(model_response, evidence) if model_response else ""
    return synthesis or _extractive_answer(question, evidence)
