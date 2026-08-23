"""The dashboard must not turn an old Playwright artifact into a false pass."""

from pathlib import Path

from myfinance_testing_api import main


class _FailedProcess:
    stdout = iter(["Running 1 test"])

    def wait(self) -> int:
        return 1


def test_visual_check_removes_a_stale_report_before_running(monkeypatch, tmp_path: Path) -> None:
    report = tmp_path / "playwright-results.json"
    report.write_text('{"stats": {"startTime": "old"}, "suites": []}', encoding="utf-8")
    updates: list[dict] = []
    captured_environment: dict[str, str] = {}

    def start_process(*_, **kwargs):
        captured_environment.update(kwargs["env"])
        return _FailedProcess()

    monkeypatch.setattr(main, "PLAYWRIGHT_REPORT_PATH", report)
    monkeypatch.setattr(main, "PLAYWRIGHT_WORKDIR", tmp_path)
    monkeypatch.delenv("MYFINANCE_PLAYWRIGHT_VISIBLE", raising=False)
    monkeypatch.delenv("MYFINANCE_PLAYWRIGHT_DISPLAY", raising=False)
    monkeypatch.setattr(main.subprocess, "Popen", start_process)
    monkeypatch.setattr(main, "_update_visual_check", lambda *_, **kwargs: updates.append(kwargs))
    monkeypatch.setattr(main, "_visual_check_event", lambda *_: None)

    main._run_visual_check("VISUAL-TEST")

    assert not report.exists()
    assert captured_environment["MYFINANCE_PLAYWRIGHT_VISIBLE"] == "0"
    assert captured_environment["MYFINANCE_PLAYWRIGHT_API_URL"] == main.CHAT_API_URL
    assert updates[-1]["status"] == "failed"
