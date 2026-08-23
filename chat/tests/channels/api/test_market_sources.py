from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from myfinance_agent_market.availability import market_answer_availability
from myfinance_agent_market.collector import collect_current_market_snapshot, record_collection_run
from myfinance_agent_market.main import app
from myfinance_agent_market.market_watch import MARKET_WATCH_URL, market_watch_collection_status
from myfinance_agent_market.monitoring import collection_health
from myfinance_agent_market.sources import (
    active_market_sources,
    market_collection_plan,
    market_instrument_registry,
    market_source_registry,
)
from myfinance_agent_market.storage import MarketObservationStore
from myfinance_contracts import MarketObservation

client = TestClient(app)


def test_market_source_registry_declares_only_the_new_official_site_as_market_source() -> None:
    policy, sources = market_source_registry()

    assert policy["require_dated_observation"] is True
    assert policy["allow_market_answer_only_with_verified_observation"] is True
    assert [source.source_id for source in sources] == ["tunis_stock_exchange_official", "cmf_official"]
    assert sources[0].base_url == "https://tunis-stockexchange.com"
    assert sources[0].activation_status == "active"
    assert sources[1].activation_status == "candidate"
    assert [source.source_id for source in active_market_sources()] == ["tunis_stock_exchange_official"]


def test_market_status_exposes_the_active_official_market_source() -> None:
    response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["status"] == "market_answers_ready"
    assert response.json()["active_source_ids"] == ["tunis_stock_exchange_official"]
    assert response.json()["verified_source_ids"] == []


def test_market_answer_availability_exposes_verified_listed_instruments() -> None:
    availability = market_answer_availability(["biat", "zitouna"])

    assert availability["status"] == "market_answers_ready"
    assert availability["active"] is True
    assert availability["active_source_ids"] == ["tunis_stock_exchange_official"]
    assert [item["bank_name"] for item in availability["requested_instruments"]] == ["BIAT", "Banque Zitouna"]
    assert availability["unmapped_bank_ids"] == ["zitouna"]


def test_market_availability_endpoint_is_read_only() -> None:
    response = client.get("/answer-availability?bank_id=biat")

    assert response.status_code == 200
    assert response.json()["status"] == "market_answers_ready"
    instrument = response.json()["requested_instruments"][0]
    assert instrument["identity_status"] == "verified"
    assert instrument["instrument_id"] == "BVMT:BIAT"


def test_market_instruments_are_mapped_from_the_verified_official_reference() -> None:
    instruments = market_instrument_registry()

    listed = [item for item in instruments if item.listing_status == "listed"]
    assert [item.instrument_id for item in listed] == ["BVMT:AB", "BVMT:TJARI", "BVMT:BIAT", "BVMT:BT"]
    assert all(item.identity_status == "verified" for item in listed)
    plan = market_collection_plan("biat")
    assert plan["status"] == "active"
    assert market_collection_plan("zitouna")["status"] == "instrument_not_available"


def test_market_watch_exposes_the_scheduled_snapshot_collection_boundary() -> None:
    status = market_watch_collection_status()

    assert status == {
        "source_id": "tunis_stock_exchange_official",
        "status": "scheduled_snapshot_collection_ready",
        "source_url": MARKET_WATCH_URL,
        "reason": "The official reader captures the displayed public quote; a scheduler persists each verified collection as an immutable snapshot.",
    }


def test_storage_keeps_one_dated_source_snapshot_when_a_future_export_is_verified(tmp_path) -> None:
    retrieved_at = datetime(2026, 8, 12, 8, 30, tzinfo=UTC)
    observation = MarketObservation(
        instrument_id="BVMT:BIAT",
        field="last_price",
        value=Decimal("92.70"),
        observed_at=datetime(2026, 8, 11, 13, tzinfo=UTC),
        retrieved_at=retrieved_at,
        source_id="tunis_stock_exchange_official",
        source_url=MARKET_WATCH_URL,
        verification_status="verified",
    )

    destination = MarketObservationStore(tmp_path).save_snapshot([observation], retrieved_at=retrieved_at)

    assert destination.name.startswith("tunis_stock_exchange_official-")


def test_collector_persists_the_official_reader_result_without_a_chat_read(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "myfinance_agent_market.collector.current_market_quotes",
        lambda _bank_ids: [{
            "bank_id": "biat", "mnemonic": "BIAT", "price": 100.5,
            "change_percent": -0.25, "currency": "Dinar Tunisien",
            "source_url": MARKET_WATCH_URL, "retrieved_at": "2026-08-12T08:30:00Z",
        }],
    )

    result = collect_current_market_snapshot(["biat"], root=tmp_path)
    points = MarketObservationStore(tmp_path).load_price_points("BVMT:BIAT", year=2026)

    assert result["observation_count"] == 2
    assert points == [{
        "date": "2026-08-12", "close": 100.5, "source_url": MARKET_WATCH_URL,
        "retrieved_at": "2026-08-12T08:30:00+00:00",
    }]


def test_collection_health_marks_an_old_snapshot_as_stale(tmp_path) -> None:
    retrieved_at = datetime(2026, 8, 12, 8, 30, tzinfo=UTC)
    observation = MarketObservation(
        instrument_id="BVMT:BIAT", field="last_price", value=Decimal("92.70"),
        observed_at=retrieved_at, retrieved_at=retrieved_at,
        source_id="tunis_stock_exchange_official", source_url=MARKET_WATCH_URL,
        verification_status="verified",
    )
    MarketObservationStore(tmp_path).save_snapshot([observation], retrieved_at=retrieved_at)

    health = collection_health(tmp_path, now=datetime(2026, 8, 12, 9, 16, tzinfo=UTC))

    assert health["status"] == "stale"
    assert health["snapshot_count"] == 1


def test_collection_health_exposes_a_critical_alert_after_a_failed_run(tmp_path) -> None:
    snapshots_root = tmp_path / "snapshots"
    retrieved_at = datetime(2026, 8, 12, 8, 30, tzinfo=UTC)
    observation = MarketObservation(
        instrument_id="BVMT:BIAT", field="last_price", value=Decimal("92.70"),
        observed_at=retrieved_at, retrieved_at=retrieved_at,
        source_id="tunis_stock_exchange_official", source_url=MARKET_WATCH_URL,
        verification_status="verified",
    )
    MarketObservationStore(snapshots_root).save_snapshot([observation], retrieved_at=retrieved_at)
    record_collection_run(
        "failed", started_at=datetime(2026, 8, 12, 8, 31, tzinfo=UTC),
        finished_at=datetime(2026, 8, 12, 8, 32, tzinfo=UTC),
        details={"error_type": "TimeoutError", "error": "official source timed out"},
        root=tmp_path / "runs",
    )

    health = collection_health(
        snapshots_root, runs_root=tmp_path / "runs", now=datetime(2026, 8, 12, 8, 35, tzinfo=UTC),
    )

    assert health["status"] == "collection_failed"
    assert health["fresh"] is False
    assert health["latest_run"] == {
        "status": "failed", "started_at": "2026-08-12T08:31:00+00:00",
        "finished_at": "2026-08-12T08:32:00+00:00",
        "error_type": "TimeoutError", "error": "official source timed out",
    }
    assert health["alerts"][0]["code"] == "collection_failed"
