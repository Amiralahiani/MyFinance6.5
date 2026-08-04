"""Human-readable Markdown and HTML rendering for one autonomous API test."""

from __future__ import annotations

from html import escape
from pathlib import Path

from myfinance_autotest.models import ApiPrototypeReport


def _markdown(report: ApiPrototypeReport) -> str:
    lines = [
        f"# Autonomous report — {report.test_id}",
        "",
        f"- Verdict: **{report.verdict.value.upper()}**",
        f"- Endpoint: `{report.endpoint}`",
        f"- Duration: {report.duration_ms} ms",
        f"- Issue categories: {', '.join(item.value for item in report.failure_categories) or 'none'}",
        "",
        "## Deterministic checks",
        "",
        "| Check | Result | Expected | Actual |",
        "| --- | --- | --- | --- |",
    ]
    for check in report.checks:
        result = "PASS" if check.passed else "FAIL" if check.passed is False else "N/A"
        lines.append(f"| {check.name} | {result} | {check.expected} | {check.actual} |")
    if report.grounding:
        lines.extend(["", "## Financial evidence"])
        if report.grounding.evidence:
            for evidence in report.grounding.evidence:
                lines.extend(
                    [
                        f"- Document: `{evidence.source_path}`",
                        f"- Page: {evidence.page_number}",
                        f"- Excerpt: {evidence.excerpt}",
                    ]
                )
        else:
            lines.append("No automatically validated evidence is available.")
    if report.evaluation:
        lines.extend(
            [
                "",
                "## Groq qualitative evaluation",
                "",
                f"Qualitative verdict: **{report.evaluation.verdict.value.upper()}** · relevance {report.evaluation.relevance}/5 · clarity {report.evaluation.clarity}/5.",
                report.evaluation.rationale,
            ]
        )
    if report.critic_decision:
        lines.extend(["", "## Critic decision", "", report.critic_decision.reason])
    if report.regression:
        lines.extend(["", "## Recorded regression", "", f"`{report.regression.regression_id}`"])
    return "\n".join(lines) + "\n"


def write_rendered_api_report(report: ApiPrototypeReport, root: Path) -> tuple[Path, Path]:
    """Write stable Markdown and safe HTML views beside the JSON report."""

    folder = root / report.run_id
    folder.mkdir(parents=True, exist_ok=True)
    markdown_path = folder / f"{report.test_id}.md"
    html_path = folder / f"{report.test_id}.html"
    markdown = _markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    body = escape(markdown)
    html_path.write_text(
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<title>Autonomous report</title><style>body{font-family:system-ui;margin:2rem;max-width:1000px}pre{white-space:pre-wrap}</style>"
        f"<body><pre>{body}</pre></body></html>\n",
        encoding="utf-8",
    )
    return markdown_path, html_path
