"""Build the reproducible scenario library for all catalogued reports."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "shared" / "contracts" / "src"),
    str(ROOT / "chat" / "knowledge" / "src"),
    str(ROOT / "chat" / "api" / "src"),
]

from myfinance_autotest.scenarios.library import build_scenario_library, write_scenario_library


def main() -> None:
    library = build_scenario_library()
    path = write_scenario_library(library)
    print(
        f"{library.report_count} rapports · {library.auto_validated_fact_scenario_count} faits · "
        f"{library.cross_channel_scenario_count} croisements API-Web · "
        f"{library.missing_fact_scenario_count} absences explicites · {path}"
    )


if __name__ == "__main__":
    main()
