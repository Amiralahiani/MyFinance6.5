"""Write an atomic JSON report for the first API vertical slice."""

from __future__ import annotations

from pathlib import Path

from myfinance_autotest.models import ApiPrototypeReport


def write_api_prototype_report(report: ApiPrototypeReport, root: Path) -> Path:
    path = root / report.run_id / f"{report.test_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path
