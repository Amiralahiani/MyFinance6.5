"""Web executor contract tests without opening a browser."""

from __future__ import annotations

import json
import subprocess

from myfinance_autotest import models
from myfinance_autotest.executors.web import WebExecutor


def _action(channel: models.Channel = models.Channel.WEB) -> models.PlannedAction:
    return models.PlannedAction(
        action_id="WEB-001",
        objective_id="OBJ-001",
        kind=models.ActionKind.SEND_MESSAGE,
        channel=channel,
        rationale="Envoyer la question à la vraie interface Web.",
        question="Quel est le PNB de BIAT en 2025 ?",
    )


def test_web_executor_normalises_playwright_observations(tmp_path) -> None:
    calls: list[dict] = []

    def runner(*args, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "response": {"type": "numeric"},
                    "visible_text": "1 594 799",
                    "screenshot_paths": ["C:/tmp/web.png"],
                    "console_errors": [],
                    "network_errors": [],
                }
            ),
            stderr="",
        )

    result = WebExecutor("http://127.0.0.1:3000", screenshot_root=tmp_path, runner=runner).execute(_action())

    assert result.channel is models.Channel.WEB
    assert result.response == {"type": "numeric"}
    assert result.visible_text == "1 594 799"
    sent = json.loads(calls[0]["input"])
    assert sent["question"] == "Quel est le PNB de BIAT en 2025 ?"
    assert sent["base_url"] == "http://127.0.0.1:3000"


def test_web_executor_rejects_an_api_action_before_launching_playwright() -> None:
    executor = WebExecutor("http://127.0.0.1:3000", runner=lambda **_: None)

    try:
        executor.execute(_action(models.Channel.API))
    except ValueError as error:
        assert "WEB" in str(error)
    else:
        raise AssertionError("The executor must reject an API action.")
