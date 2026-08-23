"""Current quote reader for the official public Bourse de Tunis Market Watch."""

from __future__ import annotations

import json
import subprocess
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from myfinance_agent_docs.catalog import bank_definitions

from myfinance_agent_market.storage import MarketObservationStore

PROJECT_ROOT = Path(__file__).resolve().parents[4]
REFERENCE_URL = "https://tunis-stockexchange.com/sites/default/files/bourse_referentiel/referentiel.json"
READER_SCRIPT = PROJECT_ROOT / "chat" / "web" / "scripts" / "read_market_watch.mjs"
SUMMARY_READER_SCRIPT = PROJECT_ROOT / "chat" / "web" / "scripts" / "read_market_summary.mjs"
HISTORY_READER_SCRIPT = PROJECT_ROOT / "chat" / "web" / "scripts" / "read_market_history.mjs"
MARKET_SNAPSHOTS_ROOT = PROJECT_ROOT / "data" / "market-snapshots"


class MarketWatchUnavailable(RuntimeError):
    """The public market display could not provide a safe current quote."""


def current_market_quote(bank_id: str) -> dict[str, Any]:
    """Read the current displayed quote through official public interfaces only."""
    return current_market_quotes([bank_id])[0]


def current_market_quotes(bank_ids: list[str]) -> list[dict[str, Any]]:
    """Read several displayed quotes in one official Market Watch browser session."""
    if not bank_ids:
        return []
    instruments = [(bank_id, _official_main_instrument(bank_id)) for bank_id in bank_ids]
    try:
        completed = subprocess.run(
            ["node", str(READER_SCRIPT), *(instrument["mnemo"] for _, instrument in instruments)],
            cwd=PROJECT_ROOT / "chat" / "web",
            capture_output=True,
            check=True,
            text=True,
            timeout=55,
        )
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise MarketWatchUnavailable("The official Market Watch quote could not be read right now.") from error
    quotes = payload.get("quotes") if isinstance(payload, dict) else None
    if not isinstance(quotes, list):
        raise MarketWatchUnavailable("The official Market Watch returned an invalid quote.")
    displayed = {quote.get("mnemonic"): quote for quote in quotes if isinstance(quote, dict)}
    result: list[dict[str, Any]] = []
    for bank_id, instrument in instruments:
        quote = displayed.get(instrument["mnemo"])
        if not quote:
            raise MarketWatchUnavailable("The official Market Watch returned an incomplete comparison.")
        price = _number(quote.get("displayed_price"))
        change = _number(quote.get("displayed_change"))
        if price is None or change is None:
            raise MarketWatchUnavailable("The official Market Watch quote is incomplete.")
        result.append({
            "bank_id": bank_id,
            "bank_name": bank_definitions()[bank_id][0],
            "mnemonic": instrument["mnemo"],
            "isin": instrument["isincode"],
            "price": price,
            "change_percent": change,
            "currency": instrument["unite_De_Cotation"],
            "source_url": payload.get("source_url"),
            "retrieved_at": payload.get("retrieved_at"),
            "delay_notice": payload.get("delay_notice"),
        })
    return result


def current_market_summary() -> dict[str, Any]:
    """Read the public, delayed whole-market session summary from Market Watch."""
    try:
        completed = subprocess.run(
            ["node", str(SUMMARY_READER_SCRIPT)],
            cwd=PROJECT_ROOT / "chat" / "web",
            capture_output=True,
            check=True,
            text=True,
            timeout=65,
        )
        summary = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise MarketWatchUnavailable("The official Market Watch session summary could not be read right now.") from error
    if not isinstance(summary, dict):
        raise MarketWatchUnavailable("The official Market Watch returned an invalid session summary.")
    numeric_fields = (
        "market_capitalization_tnd", "traded_value_tnd", "traded_quantity",
        "transactions", "advances", "declines",
    )
    parsed = {field: _number(str(summary.get(field, ""))) for field in numeric_fields}
    active_values = summary.get("active_values")
    if any(value is None for value in parsed.values()) or not isinstance(active_values, str) or "/" not in active_values:
        raise MarketWatchUnavailable("The official Market Watch session summary is incomplete.")
    active, listed = active_values.split("/", 1)
    active_count = _number(active)
    listed_count = _number(listed)
    if active_count is None or listed_count is None:
        raise MarketWatchUnavailable("The official Market Watch active-value count is invalid.")
    return {
        **parsed,
        "active_values": int(active_count),
        "listed_values": int(listed_count),
        "source_url": summary.get("source_url"),
        "retrieved_at": summary.get("retrieved_at"),
        "delay_notice": summary.get("delay_notice"),
    }


def historical_market_performance(
    bank_id: str,
    year: int,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Read one bank's official daily historical series for a calendar year.

    Dated local snapshots take precedence once enough observations exist.  The
    official append-only NDJSON history remains the bootstrap source until the
    scheduled collector has accumulated a usable local series.
    """
    if year < 2000 or year > 2100:
        raise MarketWatchUnavailable("A valid calendar year is required for historical market data.")
    start, end = _period_bounds(year, start_date, end_date)
    instrument = _official_main_instrument(bank_id)
    stored_points = MarketObservationStore(MARKET_SNAPSHOTS_ROOT).load_price_points(
        f"BVMT:{instrument['mnemo']}", year=year
    )
    stored_points = _filter_points(stored_points, start, end)
    if len(stored_points) >= 2:
        return _performance_payload(
            bank_id,
            instrument,
            year,
            stored_points,
            source_url=str(stored_points[-1]["source_url"]),
            retrieved_at=str(stored_points[-1]["retrieved_at"]),
            series_origin="stored_snapshots",
        )
    try:
        completed = subprocess.run(
            ["node", str(HISTORY_READER_SCRIPT), instrument["mnemo"], str(year)],
            cwd=PROJECT_ROOT / "chat" / "web",
            capture_output=True,
            check=True,
            text=True,
            timeout=180,
        )
        history = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise MarketWatchUnavailable("The official historical market dataset could not be read right now.") from error
    points = history.get("points") if isinstance(history, dict) else None
    if not isinstance(points, list) or len(points) < 2:
        raise MarketWatchUnavailable("No usable official history is available for this bank and year.")
    points = _filter_points(points, start, end)
    if len(points) < 2:
        raise MarketWatchUnavailable("No usable official history is available for that date range.")
    return _performance_payload(
        bank_id,
        instrument,
        year,
        points,
        source_url=history.get("source_url"),
        retrieved_at=history.get("retrieved_at"),
        series_origin="official_history",
        last_observation_date=history.get("last_observation_date"),
    )


def historical_market_performance_range(
    bank_id: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Calculate one traceable performance over an explicit multi-year range."""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as error:
        raise MarketWatchUnavailable("Historical date boundaries must use YYYY-MM-DD.") from error
    if start > end:
        raise MarketWatchUnavailable("The start of a historical range must precede its end.")
    if end.year - start.year > 5:
        raise MarketWatchUnavailable("A historical range may cover at most six calendar years.")
    performances = [historical_market_performance(bank_id, year) for year in range(start.year, end.year + 1)]
    points = [
        point
        for performance in performances
        for point in performance["points"]
        if start_date <= str(point.get("date", "")) <= end_date
    ]
    if len(points) < 2:
        raise MarketWatchUnavailable("No usable official history is available for that date range.")
    first = performances[0]
    origins = {str(performance.get("series_origin")) for performance in performances}
    return _performance_payload(
        bank_id,
        {"mnemo": str(first["mnemonic"]), "isincode": str(first["isin"]), "unite_De_Cotation": str(first["currency"])},
        start.year,
        points,
        source_url=performances[-1]["source_url"],
        retrieved_at=performances[-1]["retrieved_at"],
        series_origin=origins.pop() if len(origins) == 1 else "mixed_sources",
        last_observation_date=points[-1].get("date"),
    )


def _period_bounds(year: int, start_date: str | None, end_date: str | None) -> tuple[str | None, str | None]:
    try:
        start = date.fromisoformat(start_date).isoformat() if start_date else None
        end = date.fromisoformat(end_date).isoformat() if end_date else None
    except ValueError as error:
        raise MarketWatchUnavailable("Historical date boundaries must use YYYY-MM-DD.") from error
    if (start and not start.startswith(f"{year}-")) or (end and not end.startswith(f"{year}-")):
        raise MarketWatchUnavailable("A historical date range must stay within one calendar year.")
    if start and end and start > end:
        raise MarketWatchUnavailable("The start of a historical range must precede its end.")
    return start, end


def _filter_points(points: list[dict[str, Any]], start: str | None, end: str | None) -> list[dict[str, Any]]:
    return [
        point
        for point in points
        if isinstance(point, dict)
        and isinstance(point.get("date"), str)
        and (start is None or point["date"] >= start)
        and (end is None or point["date"] <= end)
    ]


def _performance_payload(
    bank_id: str,
    instrument: dict[str, str],
    year: int,
    points: list[dict[str, Any]],
    *,
    source_url: object,
    retrieved_at: object,
    series_origin: str,
    last_observation_date: object | None = None,
) -> dict[str, Any]:
    first, last = points[0], points[-1]
    if not all(isinstance(point, dict) for point in (first, last)):
        raise MarketWatchUnavailable("The market history is invalid.")
    first_close = first.get("close")
    last_close = last.get("close")
    if not isinstance(first_close, (int, float)) or not isinstance(last_close, (int, float)) or first_close == 0:
        raise MarketWatchUnavailable("The market history has no valid opening or closing price.")
    return {
        "bank_id": bank_id,
        "bank_name": bank_definitions()[bank_id][0],
        "mnemonic": instrument["mnemo"],
        "isin": instrument["isincode"],
        "currency": instrument["unite_De_Cotation"],
        "year": year,
        "first_close": float(first_close),
        "first_date": first.get("date"),
        "last_close": float(last_close),
        "last_date": last.get("date"),
        "performance_percent": round((float(last_close) / float(first_close) - 1) * 100, 2),
        "points": points,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "last_observation_date": last_observation_date or last.get("date"),
        "series_origin": series_origin,
    }


def _official_main_instrument(bank_id: str) -> dict[str, str]:
    try:
        bank_name = bank_definitions()[bank_id][0]
    except KeyError as error:
        raise MarketWatchUnavailable("This bank is not available in the report universe.") from error
    request = Request(REFERENCE_URL, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            entries = json.loads(response.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MarketWatchUnavailable("The official issuer reference could not be read right now.") from error
    return _find_main_instrument(entries, bank_name)


def _find_main_instrument(entries: object, bank_name: str) -> dict[str, str]:
    if not isinstance(entries, list):
        raise MarketWatchUnavailable("The official issuer reference is invalid.")
    expected = _normalise(bank_name)
    candidates = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("grp_description") == "Ligne Mère"
        and expected in {
            _normalise(str(entry.get("lib_valeur", ""))),
            _normalise(str(entry.get("emetteur", ""))),
        }
    ]
    if len(candidates) != 1:
        raise MarketWatchUnavailable("No unique official listed instrument was found for this bank.")
    candidate = candidates[0]
    if not all(isinstance(candidate.get(key), str) and candidate[key] for key in ("mnemo", "isincode", "unite_De_Cotation")):
        raise MarketWatchUnavailable("The official instrument reference is incomplete.")
    return {key: candidate[key] for key in ("mnemo", "isincode", "unite_De_Cotation")}


def _number(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    cleaned = value.replace(" ", "").replace(",", ".").replace("%", "").strip("()")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalise(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(character) != "Mn"
    )
