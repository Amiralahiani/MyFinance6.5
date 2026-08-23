"""Local, append-only storage for verified market observations."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from myfinance_contracts import MarketObservation


class MarketObservationStore:
    """Persist one fetch as an immutable, source-labelled snapshot."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def save_snapshot(
        self,
        observations: list[MarketObservation],
        *,
        retrieved_at: datetime,
    ) -> Path:
        if not observations:
            raise ValueError("Refusing to persist an empty market snapshot.")
        if any(item.verification_status != "verified" for item in observations):
            raise ValueError("Only verified observations may be persisted.")
        retrieval = retrieved_at.astimezone(UTC)
        folder = self.root / retrieval.strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        source_ids = {item.source_id for item in observations}
        if len(source_ids) != 1:
            raise ValueError("A snapshot must contain observations from exactly one source.")
        source_id = source_ids.pop()
        filename = f"{source_id}-{retrieval.strftime('%Y%m%dT%H%M%SZ')}.json"
        destination = folder / filename
        if destination.exists():
            raise FileExistsError(f"Snapshot already exists: {destination}")
        payload = {
            "schema_version": "1.0",
            "retrieved_at": retrieval.isoformat(),
            "source_id": source_id,
            "observations": [item.model_dump(mode="json") for item in observations],
        }
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)
        return destination

    def load_price_points(
        self,
        instrument_id: str,
        *,
        year: int,
    ) -> list[dict[str, object]]:
        """Return one auditable closing point per stored retrieval date.

        A snapshot is immutable, whereas a user-facing history needs a compact
        daily series.  If the collector ran more than once on a day, the last
        retrieved quote is retained for that day.  No external market value is
        mixed into this result.
        """
        latest_by_day: dict[str, MarketObservation] = {}
        for observation in self._observations():
            if (
                observation.instrument_id != instrument_id
                or observation.field != "last_price"
                or observation.observed_at.year != year
            ):
                continue
            day = observation.observed_at.date().isoformat()
            previous = latest_by_day.get(day)
            if previous is None or observation.retrieved_at > previous.retrieved_at:
                latest_by_day[day] = observation
        return [
            {
                "date": day,
                "close": float(observation.value),
                "source_url": observation.source_url,
                "retrieved_at": observation.retrieved_at.isoformat(),
            }
            for day, observation in sorted(latest_by_day.items())
        ]

    def _observations(self) -> Iterable[MarketObservation]:
        if not self.root.exists():
            return []
        observations: list[MarketObservation] = []
        for path in sorted(self.root.rglob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                items = payload.get("observations", [])
                observations.extend(MarketObservation.model_validate(item) for item in items)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                # A malformed local file must not become market evidence.
                continue
        return observations
