"""Run a selected reproducible E2E batch against already-running local services."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "shared" / "contracts" / "src"),
    str(ROOT / "chat" / "knowledge" / "src"),
    str(ROOT / "chat" / "api" / "src"),
]

from myfinance_autotest.campaign_runner import run_scenario_batch, write_campaign_report
from myfinance_autotest.config import load_settings
from myfinance_autotest.executors.api import ApiExecutor
from myfinance_autotest.executors.web import WebExecutor
from myfinance_autotest.scenarios.library import build_scenario_library
from myfinance_autotest.tools.groq_client import GroqClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a selected MyFinance autonomous E2E campaign.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--web-url", default="http://127.0.0.1:3000")
    parser.add_argument("--max-scenarios", type=int, default=10)
    parser.add_argument("--include-cross-channel", action="store_true")
    parser.add_argument("--with-groq", action="store_true", help="Add Groq Evaluator and Critic to each selected scenario.")
    parser.add_argument("--output-root", type=Path, default=ROOT / "data" / "autotest" / "campaigns")
    args = parser.parse_args()
    settings = load_settings() if args.with_groq else None
    if settings is not None:
        settings.require_groq_api_key()
    api = ApiExecutor(args.api_url)
    try:
        report = run_scenario_batch(
            build_scenario_library(),
            api_executor=api,
            web_executor=WebExecutor(args.web_url) if args.include_cross_channel else None,
            max_scenarios=args.max_scenarios,
            include_cross_channel=args.include_cross_channel,
            settings=settings,
            groq_client=GroqClient(settings) if settings is not None else None,
            regression_root=ROOT / "data" / "autotest" / "regressions",
        )
    finally:
        api.close()
    json_path, markdown_path, html_path = write_campaign_report(report, args.output_root)
    print(f"Campagne : {json_path}\nMarkdown : {markdown_path}\nHTML : {html_path}")


if __name__ == "__main__":
    main()
