"""Read-only health checks for the scheduled market collector."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from myfinance_agent_market.collector import (
    MARKET_COLLECTION_RUNS_ROOT,
    MARKET_SNAPSHOTS_ROOT,
    latest_collection_run,
)


def collection_health(
    root: Path = MARKET_SNAPSHOTS_ROOT,
    *,
    runs_root: Path = MARKET_COLLECTION_RUNS_ROOT,
    now: datetime | None = None,
    expected_interval_minutes: int = 30,
) -> dict[str, object]:
    """Report snapshot freshness and the latest scheduler outcome without fetching quotes."""
    snapshots = sorted(root.rglob("*.json")) if root.exists() else []
    latest_run = latest_collection_run(runs_root)
    run_details = _run_details(latest_run)
    if not snapshots:
        response = {
            "status": "no_snapshots", "fresh": False, "snapshot_count": 0,
            "expected_interval_minutes": expected_interval_minutes,
        }
        return _with_alerts(response, latest_run, run_details)
    latest = snapshots[-1]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
        retrieved_at = datetime.fromisoformat(str(payload["retrieved_at"]))
        observation_count = len(payload["observations"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        response = {
            "status": "invalid_latest_snapshot", "fresh": False, "snapshot_count": len(snapshots),
            "expected_interval_minutes": expected_interval_minutes,
        }
        return _with_alerts(response, latest_run, run_details)
    reference = (now or datetime.now(UTC)).astimezone(UTC)
    age_minutes = max(0, round((reference - retrieved_at.astimezone(UTC)).total_seconds() / 60, 1))
    fresh = age_minutes <= expected_interval_minutes * 1.5
    response = {
        "status": "fresh" if fresh else "stale",
        "fresh": fresh,
        "snapshot_count": len(snapshots),
        "latest_snapshot": str(latest),
        "retrieved_at": retrieved_at.astimezone(UTC).isoformat(),
        "age_minutes": age_minutes,
        "observation_count": observation_count,
        "expected_interval_minutes": expected_interval_minutes,
    }
    return _with_alerts(response, latest_run, run_details)


def _run_details(latest_run: dict[str, object] | None) -> dict[str, object] | None:
    if latest_run is None:
        return None
    return {
        "status": latest_run["status"],
        "started_at": latest_run.get("started_at"),
        "finished_at": latest_run.get("finished_at"),
        "error_type": latest_run.get("details", {}).get("error_type") if isinstance(latest_run.get("details"), dict) else None,
        "error": latest_run.get("details", {}).get("error") if isinstance(latest_run.get("details"), dict) else None,
    }


def _with_alerts(
    response: dict[str, object],
    latest_run: dict[str, object] | None,
    run_details: dict[str, object] | None,
) -> dict[str, object]:
    alerts: list[dict[str, str]] = []
    if response["status"] != "fresh":
        alerts.append({
            "code": "snapshot_not_current",
            "severity": "warning",
            "message": "Market snapshots are not current; historical answers must state their data coverage.",
        })
    if latest_run and latest_run["status"] == "failed":
        response["status"] = "collection_failed"
        response["fresh"] = False
        alerts.append({
            "code": "collection_failed",
            "severity": "critical",
            "message": "The latest scheduled market collection failed. Review the recorded error before relying on new history.",
        })
    response["latest_run"] = run_details
    response["alerts"] = alerts
    return response
