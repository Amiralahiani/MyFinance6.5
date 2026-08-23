"""Cooperative stop controls for release-validation campaigns."""

import json
from datetime import UTC, datetime

from fastapi import BackgroundTasks
from myfinance_testing_api import main


def test_stop_request_finishes_a_campaign_as_cancelled(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "testing.sqlite")
    campaign_id = "CAMPAIGN-stop-test"
    timestamp = datetime.now(UTC).isoformat()
    with main._connection() as connection:
        connection.execute(
            "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, NULL, NULL)",
            (campaign_id, "running", timestamp, timestamp, json.dumps({"scenario_profile": "catalog"})),
        )

    result = main.stop_catalog_campaign(campaign_id)

    assert result == {"id": campaign_id, "status": "cancelling"}
    assert main._campaign_cancellation_requested(campaign_id) is True

    main._finish_cancelled_campaign(campaign_id, stage="executor", completed=4, total=211)

    campaign = main._read_campaign(campaign_id)
    assert campaign["status"] == "cancelled"
    assert campaign["events"][-1]["type"] == "campaign_cancelled"
    assert campaign["events"][-1]["completed"] == 4


def test_orphaned_stop_is_recovered_as_cancelled_when_campaigns_are_read(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "testing.sqlite")
    monkeypatch.setattr(main, "ACTIVE_CAMPAIGN_IDS", set())
    campaign_id = "CAMPAIGN-orphaned-stop"
    timestamp = datetime.now(UTC).isoformat()
    with main._connection() as connection:
        connection.execute(
            "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, NULL, NULL)",
            (campaign_id, "cancelling", timestamp, timestamp, json.dumps({"scenario_profile": "catalog"})),
        )

    campaigns = main.list_campaigns()["campaigns"]

    assert campaigns[0]["status"] == "cancelled"
    assert campaigns[0]["result"]["stopped"] is True


def test_delete_active_campaign_is_deferred_until_its_safe_stop(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "testing.sqlite")
    monkeypatch.setattr(main, "CAMPAIGN_REPORT_ROOT", tmp_path / "campaigns")
    campaign_id = "CAMPAIGN-delete-active"
    timestamp = datetime.now(UTC).isoformat()
    with main._connection() as connection:
        connection.execute(
            "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, NULL, NULL)",
            (campaign_id, "running", timestamp, timestamp, json.dumps({"scenario_profile": "catalog"})),
        )

    response = main.Response()
    result = main.delete_campaign(campaign_id, response)

    assert response.status_code == 202
    assert result == {"id": campaign_id, "status": "cancelling", "deletion_pending": True}
    assert main._read_campaign(campaign_id)["configuration"]["delete_after_stop"] is True
    main._finish_cancelled_campaign(campaign_id, stage="executor")
    assert main.list_campaigns() == {"campaigns": []}


def test_clear_history_removes_campaign_records_and_only_report_artifacts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "testing.sqlite")
    report_root = tmp_path / "campaigns"
    monkeypatch.setattr(main, "CAMPAIGN_REPORT_ROOT", report_root)
    timestamp = datetime.now(UTC).isoformat()
    with main._connection() as connection:
        connection.execute(
            "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, NULL, NULL)",
            ("CAMPAIGN-old", "completed", timestamp, timestamp, json.dumps({"scenario_profile": "catalog"})),
        )
        connection.execute(
            "INSERT INTO campaign_events(campaign_id, created_at, type, data) VALUES (?, ?, ?, ?)",
            ("CAMPAIGN-old", timestamp, "campaign_completed", "{}"),
        )
    report_file = report_root / "RUN-old" / "summary.md"
    report_file.parent.mkdir(parents=True)
    report_file.write_text("old report", encoding="utf-8")

    result = main.clear_campaign_history()

    assert result == {"deleted_campaigns": 1, "status": "cleared"}
    assert main.list_campaigns() == {"campaigns": []}
    assert list(report_root.iterdir()) == []


def test_stopped_catalog_campaign_can_be_resumed_and_deleted(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "DATABASE_PATH", tmp_path / "testing.sqlite")
    report_root = tmp_path / "campaigns"
    monkeypatch.setattr(main, "CAMPAIGN_REPORT_ROOT", report_root)
    campaign_id = "CAMPAIGN-resume-test"
    timestamp = datetime.now(UTC).isoformat()
    configuration = {"scenario_profile": "catalog", "include_web": True, "with_groq": False, "max_scenarios": None}
    report_file = report_root / "RUN-resume-test" / "summary.md"
    report_file.parent.mkdir(parents=True)
    report_file.write_text("report", encoding="utf-8")
    result = {"report_paths": {"summary_markdown": str(report_file)}}
    with main._connection() as connection:
        connection.execute(
            "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (campaign_id, "cancelled", timestamp, timestamp, json.dumps(configuration), json.dumps(result)),
        )
        connection.execute(
            "INSERT INTO campaign_events(campaign_id, created_at, type, data) VALUES (?, ?, ?, ?)",
            (campaign_id, timestamp, "scenario_completed", json.dumps({"scenario_id": "FACT-1", "passage": "initial", "verdict": "pass"})),
        )

    tasks = BackgroundTasks()
    resumed = main.resume_catalog_campaign(campaign_id, tasks)

    assert resumed == {"id": campaign_id, "status": "starting"}
    assert main._read_campaign(campaign_id)["status"] == "pending"
    assert main._read_campaign(campaign_id)["configuration"]["resume"] is True
    assert len(tasks.tasks) == 1

    # A campaign must be stopped or completed again before its persisted history can be deleted.
    with main._connection() as connection:
        connection.execute("UPDATE campaigns SET status='completed' WHERE id=?", (campaign_id,))
    deleted = main.delete_campaign(campaign_id, main.Response())

    assert deleted == {"id": campaign_id, "status": "deleted"}
    assert main.list_campaigns() == {"campaigns": []}
    assert not report_file.parent.exists()
