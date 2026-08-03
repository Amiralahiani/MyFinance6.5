"""Append-only JSON Lines storage for correlated autonomous-test traces."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from myfinance_autotest.models import TraceEvent

_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|password|secret|token)", re.IGNORECASE)


def _safe_component(value: str) -> str:
    """Prevent a run or trace identifier from escaping the configured trace root."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", value)
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("Trace identifiers must contain at least one safe character.")
    return cleaned


def redact_secrets(value: Any) -> Any:
    """Recursively redact secret-shaped keys before serialisation."""
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    return value


class JsonlTraceStore:
    """Persist events in chronological append-only files grouped by campaign."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, run_id: str, trace_id: str) -> Path:
        return self.root / _safe_component(run_id) / f"{_safe_component(trace_id)}.jsonl"

    def append(self, event: TraceEvent) -> Path:
        path = self.path_for(event.run_id, event.trace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = event.model_dump(mode="json")
        payload["data"] = redact_secrets(payload["data"])
        with path.open("a", encoding="utf-8", newline="\n") as destination:
            destination.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        return path

    def read(self, run_id: str, trace_id: str) -> list[TraceEvent]:
        path = self.path_for(run_id, trace_id)
        if not path.exists():
            return []
        return [
            TraceEvent.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
