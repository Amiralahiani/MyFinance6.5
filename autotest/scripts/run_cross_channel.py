"""Execute one question against the running API and Web UI, then compare them."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "shared" / "contracts" / "src"),
    str(ROOT / "chat" / "knowledge" / "src"),
    str(ROOT / "chat" / "api" / "src"),
]

from myfinance_autotest import models
from myfinance_autotest.executors.api import ApiExecutor
from myfinance_autotest.executors.web import WebExecutor
from myfinance_autotest.validators.cross_channel import compare_api_and_web


def _test_case(question: str) -> models.TestCase:
    objective = models.TestObjective(
        objective_id="OBJ-CROSS-DEMO-001",
        category=models.TestCategory.CROSS_CHANNEL,
        description="Comparer une réponse API avec son rendu Web et sa preuve PDF.",
        required_properties=["same_type", "same_value", "same_source"],
        rationale="Les deux canaux doivent rendre la même information vérifiée.",
    )
    return models.TestCase(
        test_id="TEST-CROSS-DEMO-PNB-BIAT-2025",
        title="PNB BIAT 2025 API ↔ Web",
        category=models.TestCategory.CROSS_CHANNEL,
        channels=[models.Channel.API, models.Channel.WEB],
        input=question,
        objective=objective,
        bank_id="biat",
        reporting_year=2025,
        metric_id="net_banking_income",
        expected_properties=["same_type", "same_value", "same_source"],
        failure_criteria=["channel_divergence"],
        origin="cross_channel_demo",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare one real API answer with the real Web rendering.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--web-url", default="http://127.0.0.1:3000")
    parser.add_argument("--question", default="Quel est le PNB de BIAT en 2025 ?")
    parser.add_argument("--output-root", type=Path, default=ROOT / "data" / "autotest" / "cross-channel")
    args = parser.parse_args()

    test_case = _test_case(args.question)
    api_action = models.PlannedAction(
        action_id=f"{test_case.test_id}-API",
        objective_id=test_case.objective.objective_id,
        kind=models.ActionKind.SEND_MESSAGE,
        channel=models.Channel.API,
        rationale="Exécuter la question sur l’API locale.",
        question=test_case.input,
    )
    web_action = api_action.model_copy(
        update={"action_id": f"{test_case.test_id}-WEB", "channel": models.Channel.WEB, "rationale": "Exécuter la même question dans le navigateur."}
    )
    api_executor = ApiExecutor(args.api_url)
    try:
        api_execution = api_executor.execute(api_action)
    finally:
        api_executor.close()
    web_execution = WebExecutor(args.web_url).execute(web_action)
    result = compare_api_and_web(test_case, api_execution, web_execution)

    args.output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = args.output_root / f"{stamp}-{test_case.test_id}.json"
    path.write_text(
        json.dumps(
            {
                "comparison": result.model_dump(mode="json"),
                "api_execution": api_execution.model_dump(mode="json"),
                "web_execution": web_execution.model_dump(mode="json"),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{result.verdict.value.upper()} · résultat : {path}")
    if result.verdict is not models.Verdict.PASS:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
