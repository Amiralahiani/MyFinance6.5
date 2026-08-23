from datetime import UTC, datetime
from decimal import Decimal

from myfinance_agent_market import market_watch_reader
from myfinance_agent_market.storage import MarketObservationStore
from myfinance_contracts import MarketObservation


def test_official_reference_can_map_a_bank_by_issuer_when_the_quote_label_is_its_ticker() -> None:
    entries = [
        {
            "grp_description": "Ligne Mère",
            "lib_valeur": "BT",
            "emetteur": "BANQUE DE TUNISIE",
            "mnemo": "BT",
            "isincode": "TN0002200053",
            "unite_De_Cotation": "Dinar Tunisien",
        }
    ]
    instrument = market_watch_reader._find_main_instrument(entries, "Banque de Tunisie")

    assert instrument == {
        "mnemo": "BT",
        "isincode": "TN0002200053",
        "unite_De_Cotation": "Dinar Tunisien",
    }


def test_history_prefers_auditable_stored_snapshots_over_the_external_feed(monkeypatch, tmp_path) -> None:
    store = MarketObservationStore(tmp_path)
    for day, price in ((11, "100"), (12, "110")):
        retrieved_at = datetime(2026, 8, day, 16, tzinfo=UTC)
        store.save_snapshot([
            MarketObservation(
                instrument_id="BVMT:BIAT", field="last_price", value=Decimal(price),
                currency="Dinar Tunisien", observed_at=retrieved_at, retrieved_at=retrieved_at,
                source_id="tunis_stock_exchange_official",
                source_url="https://tunis-stockexchange.com/market-watch",
                verification_status="verified",
            )
        ], retrieved_at=retrieved_at)
    monkeypatch.setattr(market_watch_reader, "MARKET_SNAPSHOTS_ROOT", tmp_path)
    monkeypatch.setattr(
        market_watch_reader,
        "_official_main_instrument",
        lambda _bank_id: {"mnemo": "BIAT", "isincode": "TN0001800457", "unite_De_Cotation": "Dinar Tunisien"},
    )
    monkeypatch.setattr(
        market_watch_reader.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("external history should not be read")),
    )

    history = market_watch_reader.historical_market_performance("biat", 2026)

    assert history["series_origin"] == "stored_snapshots"
    assert history["performance_percent"] == 10.0
    assert history["points"] == [
        {"date": "2026-08-11", "close": 100.0, "source_url": "https://tunis-stockexchange.com/market-watch", "retrieved_at": "2026-08-11T16:00:00+00:00"},
        {"date": "2026-08-12", "close": 110.0, "source_url": "https://tunis-stockexchange.com/market-watch", "retrieved_at": "2026-08-12T16:00:00+00:00"},
    ]


def test_history_range_combines_two_annual_series(monkeypatch) -> None:
    monkeypatch.setattr(
        market_watch_reader,
        "historical_market_performance",
        lambda _bank_id, year: {
            "mnemonic": "BIAT", "isin": "TN0001800457", "currency": "Dinar Tunisien",
            "points": [{"date": f"{year}-12-31", "close": 100.0 if year == 2025 else 110.0}],
            "source_url": "https://official.example/history", "retrieved_at": f"{year}-12-31T12:00:00Z",
            "series_origin": "official_history",
        },
    )

    result = market_watch_reader.historical_market_performance_range("biat", "2025-12-31", "2026-12-31")

    assert result["performance_percent"] == 10.0
    assert result["first_date"] == "2025-12-31"
    assert result["last_date"] == "2026-12-31"
