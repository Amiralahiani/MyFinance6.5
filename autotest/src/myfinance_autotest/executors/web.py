"""Playwright Web executor via the project's existing Node dependency."""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from myfinance_autotest.models import ActionKind, Channel, PlannedAction, ToolExecutionResult

PROJECT_ROOT = Path(__file__).resolve().parents[4]
WEB_ROOT = PROJECT_ROOT / "chat" / "web"
BRIDGE_PATH = WEB_ROOT / "scripts" / "autotest_web_executor.mjs"
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _safe_file_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-") or "web-action"


class WebExecutor:
    """Run one controlled message through the real Web UI and collect diagnostics."""

    def __init__(
        self,
        base_url: str,
        *,
        screenshot_root: Path | None = None,
        timeout_seconds: float = 30,
        runner: Runner = subprocess.run,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.screenshot_root = screenshot_root or PROJECT_ROOT / "data" / "autotest" / "screenshots"
        self.timeout_seconds = timeout_seconds
        self._runner = runner

    def execute(self, action: PlannedAction) -> ToolExecutionResult:
        if action.channel is not Channel.WEB:
            raise ValueError("WebExecutor accepts only WEB actions.")
        if action.kind is not ActionKind.SEND_MESSAGE or not action.question:
            raise ValueError("WebExecutor supports only SEND_MESSAGE actions with a question.")

        started_at = datetime.now(UTC)
        started = time.perf_counter()
        screenshot_path = self.screenshot_root / f"{_safe_file_component(action.action_id)}.png"
        payload = {
            "base_url": self.base_url,
            "question": action.question,
            "timeout_ms": round(self.timeout_seconds * 1_000),
            "screenshot_path": str(screenshot_path),
        }
        try:
            completed = self._runner(
                ["node", str(BRIDGE_PATH)],
                cwd=WEB_ROOT,
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.timeout_seconds + 5,
                check=False,
            )
            latency_ms = round((time.perf_counter() - started) * 1_000)
        except subprocess.TimeoutExpired:
            return ToolExecutionResult(
                action_id=action.action_id,
                channel=Channel.WEB,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                latency_ms=round((time.perf_counter() - started) * 1_000),
                errors=["Playwright web executor timed out."],
            )
        if completed.returncode != 0:
            return ToolExecutionResult(
                action_id=action.action_id,
                channel=Channel.WEB,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                latency_ms=latency_ms,
                errors=[f"Playwright bridge failed (exit {completed.returncode}).", completed.stderr.strip()],
            )
        try:
            observed: dict[str, Any] = json.loads(completed.stdout or "")
        except (json.JSONDecodeError, TypeError):
            observed = {}
        if not observed.get("ok"):
            return ToolExecutionResult(
                action_id=action.action_id,
                channel=Channel.WEB,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                latency_ms=latency_ms,
                errors=["Playwright bridge did not return a successful observation."],
            )
        return ToolExecutionResult(
            action_id=action.action_id,
            channel=Channel.WEB,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            latency_ms=latency_ms,
            response=observed.get("response"),
            visible_text=observed.get("visible_text"),
            screenshot_paths=list(observed.get("screenshot_paths", [])),
            console_errors=list(observed.get("console_errors", [])),
            network_errors=list(observed.get("network_errors", [])),
        )
