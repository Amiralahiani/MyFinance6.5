"""Run a selected scenario-library batch through the deterministic E2E loop."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from uuid import uuid4

from myfinance_autotest.agents.critic import critique_evaluation
from myfinance_autotest.agents.evaluator import evaluate_response
from myfinance_autotest.config import AutotestSettings
from myfinance_autotest.executors.api import ApiExecutor
from myfinance_autotest.executors.web import WebExecutor
from myfinance_autotest.models import (
    ActionKind,
    Channel,
    DeterministicCheck,
    EvaluationResult,
    FailureCategory,
    FinalReport,
    PlannedAction,
    TestCase,
    TestCategory,
    Verdict,
)
from myfinance_autotest.regressions.registry import (
    RegressionRegistry,
    regression_from_confirmed_defect,
)
from myfinance_autotest.scenarios.library import ScenarioLibrary
from myfinance_autotest.state import CampaignState
from myfinance_autotest.tools.groq_client import GroqClient
from myfinance_autotest.validators.cross_channel import compare_api_and_web
from myfinance_autotest.validators.deterministic import (
    validate_behavior_contract,
    validate_deterministically,
    validate_expected_absence,
)


def _technical_checks(execution) -> list[DeterministicCheck]:
    if execution.channel is Channel.WEB:
        return [
            DeterministicCheck(
                check_id="campaign.web_errors",
                name="web_executor_has_no_errors",
                passed=not execution.errors and not execution.console_errors and not execution.network_errors,
                expected="no executor, console or network errors",
                actual={"executor": execution.errors, "console": execution.console_errors, "network": execution.network_errors},
            )
        ]
    return [
        DeterministicCheck(
            check_id="campaign.http_success",
            name="http_status_is_success",
            passed=execution.http_status == 200,
            expected=200,
            actual=execution.http_status,
        )
    ]


def _evaluation(test_case: TestCase, verdict: Verdict, checks, categories, evidence=None) -> EvaluationResult:
    score = 5 if verdict is Verdict.PASS else 1 if verdict is Verdict.FAIL else 3
    return EvaluationResult(
        test_id=test_case.test_id,
        verdict=verdict,
        relevance=score,
        factuality=score,
        source_fidelity=score,
        conversation_coherence=score,
        year_respect=score,
        unit_respect=score,
        clarity=score,
        format_respect=score,
        failure_category=categories[0] if categories else None,
        confidence=1.0,
        evidence=evidence or [],
        deterministic_checks=checks,
        rationale="Deterministic campaign verdict; no LLM assessment can change it.",
    )


def _api_action(test_case: TestCase, channel: Channel) -> PlannedAction:
    return PlannedAction(
        action_id=f"{test_case.test_id}-{channel.value.upper()}",
        objective_id=test_case.objective.objective_id,
        kind=ActionKind.SEND_MESSAGE,
        channel=channel,
        rationale="Exécuter le scénario de bibliothèque sur le canal sélectionné.",
        question=test_case.input,
        parameters={"context": test_case.conversation_context},
    )


def run_scenario_batch(
    library: ScenarioLibrary,
    *,
    api_executor: ApiExecutor,
    web_executor: WebExecutor | None = None,
    max_scenarios: int | None = None,
    include_cross_channel: bool = False,
    settings: AutotestSettings | None = None,
    groq_client: GroqClient | None = None,
    regression_root: Path | None = None,
    planned_actions: dict[str, PlannedAction] | None = None,
    on_execution_complete: Callable[[int, int, TestCase, dict], None] | None = None,
    on_scenario_complete: Callable[[int, int, TestCase, EvaluationResult, dict], None] | None = None,
) -> FinalReport:
    """Execute an intentionally bounded batch; the caller owns server lifecycle."""

    started_at = datetime.now(UTC)
    selected = [
        case
        for case in library.scenarios
        if include_cross_channel or case.category is not TestCategory.CROSS_CHANNEL
    ]
    if max_scenarios is not None:
        selected = selected[:max_scenarios]
    evaluations: list[EvaluationResult] = []
    regressions = []
    groq_call_count = 0
    for index, test_case in enumerate(selected, start=1):
        api_action = (planned_actions or {}).get(test_case.test_id) or _api_action(test_case, Channel.API)
        api_execution = api_executor.execute(api_action) if Channel.API in test_case.channels else None
        web_execution = None
        if test_case.category is TestCategory.CROSS_CHANNEL:
            if api_execution is None:
                raise ValueError("Cross-channel scenarios require the API channel.")
            if web_executor is None:
                from myfinance_autotest.models import DeterministicValidationResult
                validation = DeterministicValidationResult(
                    test_id=test_case.test_id,
                    verdict=Verdict.INCONCLUSIVE,
                    checks=_technical_checks(api_execution),
                    failure_categories=[FailureCategory.INSUFFICIENT_EVIDENCE],
                )
            else:
                web_execution = web_executor.execute(_api_action(test_case, Channel.WEB))
                comparison = compare_api_and_web(test_case, api_execution, web_execution)
                from myfinance_autotest.models import DeterministicValidationResult
                validation = DeterministicValidationResult(
                    test_id=test_case.test_id,
                    verdict=comparison.verdict,
                    checks=comparison.checks,
                    failure_categories=comparison.failure_categories,
                )
        else:
            execution = api_execution
            if execution is None:
                if web_executor is None:
                    raise ValueError("A Web-only scenario requires the Web executor.")
                web_execution = web_executor.execute(_api_action(test_case, Channel.WEB))
                execution = web_execution
            checks = _technical_checks(execution)
            validation = (
                validate_expected_absence(test_case, execution, checks)
                if test_case.origin == "catalog_missing_auto_validated_fact"
                else validate_deterministically(test_case, execution, checks)
                if test_case.category is TestCategory.FINANCIAL_FACT
                else validate_behavior_contract(test_case, execution, checks)
                if test_case.origin in {"catalog_behavior_contract", "groq_exploration_generator", "groq_critic_confirmation"}
                else validate_deterministically(test_case, execution, checks)
            )
        execution_data = {
            "api": {
                "http_status": api_execution.http_status if api_execution else None,
                "latency_ms": api_execution.latency_ms if api_execution else None,
                "response_type": (api_execution.response or {}).get("type") if api_execution else None,
                "response": api_execution.response if api_execution else None,
                "errors": api_execution.errors if api_execution else [],
            },
            "web": None if web_execution is None else {
                "latency_ms": web_execution.latency_ms,
                "response_type": (web_execution.response or {}).get("type"),
                "response": web_execution.response,
                "visible_text": web_execution.visible_text,
                "screenshots": web_execution.screenshot_paths,
                "errors": web_execution.errors,
            },
        }
        if on_execution_complete is not None:
            on_execution_complete(index, len(selected), test_case, execution_data)
        critic = None
        regression_data = None
        evaluator_call = None
        critic_call = None
        if groq_client is not None and settings is not None:
            state = CampaignState.initialise(test_case, settings.limits)
            evaluation, evaluator_call = evaluate_response(
                test_case, api_execution or web_execution, validation, client=groq_client, campaign=state
            )
            critic, critic_call = critique_evaluation(
                test_case, evaluation, validation, client=groq_client, campaign=state
            )
            groq_call_count += state.llm_call_count
            candidate = regression_from_confirmed_defect(test_case, validation, critic)
            if candidate is not None:
                registration = RegressionRegistry(regression_root or Path("data/autotest/regressions")).register(candidate)
                regression_data = {
                    "regression_id": registration.regression.regression_id,
                    "created": registration.created,
                    "path": str(registration.path),
                }
                if registration.created:
                    regressions.append(registration.regression)
            # A Critic request is deliberately not appended to ``selected`` here.
            # The caller must start a distinct Planner -> Executor -> Evaluator
            # confirmation pass.  Mutating this list made a Planner-approved batch
            # of N scenarios appear as N+M Executor scenarios in the UI.
        else:
            evaluation = _evaluation(
                test_case,
                validation.verdict,
                validation.checks,
                validation.failure_categories,
                validation.grounding.evidence if validation.grounding else [],
            )
        evaluations.append(evaluation)
        if on_scenario_complete is not None:
            on_scenario_complete(
                index, len(selected), test_case, evaluation,
                execution_data | {
                    "evaluator": {
                        "rationale": evaluation.rationale,
                        "probable_cause": evaluation.probable_cause,
                        "confidence": evaluation.confidence,
                        "deterministic_checks": [check.model_dump(mode="json") for check in evaluation.deterministic_checks],
                        "provider": evaluator_call.trace_data() if evaluator_call else None,
                    },
                    "critic": (
                        critic.model_dump(mode="json") | {"provider": critic_call.trace_data() if critic_call else None}
                        if critic
                        else None
                    ),
                    "regression": regression_data,
                },
            )
    run_id = f"RUN-BATCH-{uuid4().hex[:12]}"
    return FinalReport(
        run_id=run_id,
        trace_id=f"TRACE-BATCH-{uuid4().hex[:12]}",
        started_at=started_at,
        finished_at=datetime.now(UTC),
        tests=evaluations,
        regressions=regressions,
        groq_call_count=groq_call_count,
        recommendations=[
            "Verdicts are deterministic; inconclusive scenarios must be rerun using the required channel.",
            "Any API–Web divergence must be treated as a potential regression with its screenshots and evidence.",
        ],
    )


def write_campaign_report(report: FinalReport, root: Path) -> tuple[Path, Path, Path, Path, Path]:
    """Write a decision summary and a scenario-by-scenario audit alongside raw JSON."""

    folder = root / report.run_id
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / "campaign.json"
    summary_markdown_path = folder / "summary.md"
    summary_html_path = folder / "summary.html"
    audit_markdown_path = folder / "audit.md"
    audit_html_path = folder / "audit.html"
    counts = {verdict: sum(item.verdict is verdict for item in report.tests) for verdict in Verdict}
    issue_counts: dict[str, int] = {}
    for item in report.tests:
        if item.failure_category:
            issue_counts[item.failure_category.value] = issue_counts.get(item.failure_category.value, 0) + 1
    actions = {
        "unsupported_value": "Block every value not proven by an automatically validated fact and its PDF source.",
        "personal_data_scope": "Explicitly refuse access to accounts or personal data.",
        "unsupported_comparison": "Request a measurable criterion or refuse an unsourced ranking.",
        "contract_violation": "Align the response with the behavioural contract expected by the scenario.",
        "source_mismatch": "Check the document, page and excerpt before displaying an answer.",
    }
    summary_markdown = "\n".join(
        [
            f"# Campaign summary — {report.run_id}",
            "",
            "## Quick decision",
            f"- Scenarios run: **{len(report.tests)}**",
            f"- Passed: **{counts[Verdict.PASS]}**",
            f"- Issues detected: **{counts[Verdict.FAIL]}**",
            f"- To confirm: **{counts[Verdict.INCONCLUSIVE]}**",
            f"- Groq calls: **{report.groq_call_count}**",
            "",
            "## Issues to address",
            *[
                f"- **{category}**: {count} case(s) — {actions.get(category, 'Analyse the contract and add a regression test.')}"
                for category, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "",
            "## Results by scenario",
            "| Scenario | Verdict | Category |",
            "| --- | --- | --- |",
            *[
                f"| {item.test_id} | {item.verdict.value.upper()} | {item.failure_category.value if item.failure_category else '—'} |"
                for item in report.tests
            ],
            "",
            "See the audit report for deterministic checks, scores and evidence for every scenario.",
            "",
        ]
    )
    audit_lines = [
        f"# Detailed campaign audit — {report.run_id}",
        "",
        f"Period: {report.started_at.isoformat()} → {report.finished_at.isoformat()}",
        f"Scenarios: {len(report.tests)} · PASS: {counts[Verdict.PASS]} · FAIL: {counts[Verdict.FAIL]} · INCONCLUSIVE: {counts[Verdict.INCONCLUSIVE]}",
        "",
    ]
    for item in report.tests:
        audit_lines.extend(
            [
                f"## {item.test_id} — {item.verdict.value.upper()}",
                f"- Category: {item.failure_category.value if item.failure_category else '—'}",
                f"- Scores: relevance {item.relevance}/5, factuality {item.factuality}/5, source fidelity {item.source_fidelity}/5, coherence {item.conversation_coherence}/5, clarity {item.clarity}/5",
                f"- Conclusion: {item.rationale}",
            ]
        )
        if item.probable_cause:
            audit_lines.append(f"- Probable cause: {item.probable_cause}")
        audit_lines.extend(["", "### Deterministic checks"])
        audit_lines.extend(
            f"- {'✓' if check.passed else '✗'} **{check.name}** — expected: {check.expected!s}; actual: {check.actual!s}{f' ({check.detail})' if check.detail else ''}"
            for check in item.deterministic_checks
        )
        if item.evidence:
            audit_lines.extend(["", "### Evidence"])
            audit_lines.extend(
                f"- {evidence.source_path} · p. {evidence.page_number} — {' '.join(evidence.excerpt.split())[:400]}"
                for evidence in item.evidence
            )
        audit_lines.append("")
    audit_markdown = "\n".join(audit_lines)
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    summary_markdown_path.write_text(summary_markdown, encoding="utf-8")
    audit_markdown_path.write_text(audit_markdown, encoding="utf-8")

    def safe(value: object | None) -> str:
        return escape(str(value)) if value is not None else "—"

    def verdict_badge(verdict: Verdict) -> str:
        label = {Verdict.PASS: "PASS", Verdict.FAIL: "FAIL", Verdict.INCONCLUSIVE: "TO CONFIRM"}[verdict]
        return f'<span class="badge {verdict.value}">{label}</span>'

    def write_html(path: Path, title: str, body: str) -> None:
        path.write_text(
            f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{ color-scheme: light; --ink:#173637; --muted:#58706b; --line:#d9e5df; --paper:#f7faf8; --pass:#13795b; --fail:#bd3e32; --pending:#a56812; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.55 Inter, ui-sans-serif, system-ui, sans-serif; }}
    .page {{ max-width:1180px; margin:0 auto; padding:32px 20px 48px; }} .hero {{ padding:28px; border-radius:18px; background:linear-gradient(135deg,#123c39,#1c635a); color:white; }}
    .eyebrow {{ margin:0 0 6px; color:#b9dcd2; font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }} h1 {{ margin:0; font-size:clamp(25px,4vw,38px); line-height:1.15; }}
    .subtitle {{ margin:12px 0 0; color:#def0e9; }} .meta {{ margin:6px 0 0; color:var(--muted); font-size:13px; }} .hero .meta {{ color:#b9dcd2; }}
    main {{ margin-top:22px; }} section, .audit-case {{ margin-top:18px; padding:22px; border:1px solid var(--line); border-radius:14px; background:white; box-shadow:0 1px 2px #10251b0a; }}
    h2 {{ margin:0 0 14px; font-size:19px; }} h3 {{ margin:0; font-size:17px; }} .cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }}
    .card {{ padding:17px; border:1px solid var(--line); border-radius:12px; background:white; }} .card .number {{ display:block; font-size:28px; font-weight:800; line-height:1; }} .card .label {{ display:block; margin-top:7px; color:var(--muted); font-size:13px; }}
    .card.fail .number {{ color:var(--fail); }} .card.pass .number {{ color:var(--pass); }} .card.inconclusive .number {{ color:var(--pending); }}
    .badge {{ display:inline-block; padding:3px 8px; border-radius:999px; font-size:11px; font-weight:800; letter-spacing:.03em; }} .badge.pass {{ color:var(--pass); background:#e4f5ee; }} .badge.fail {{ color:var(--fail); background:#fbe9e7; }} .badge.inconclusive {{ color:var(--pending); background:#fff3db; }}
    ul {{ margin:0; padding-left:20px; }} li+li {{ margin-top:9px; }} .action {{ color:#2b4c45; }} .table-wrap {{ overflow-x:auto; }} table {{ width:100%; border-collapse:collapse; }} th {{ color:var(--muted); font-size:12px; letter-spacing:.04em; text-align:left; text-transform:uppercase; }} th,td {{ padding:11px 10px; border-bottom:1px solid var(--line); vertical-align:top; }} tr:last-child td {{ border-bottom:0; }}
    details {{ padding:0; }} details+details {{ margin-top:14px; }} summary {{ display:flex; align-items:center; gap:10px; cursor:pointer; list-style:none; }} summary::-webkit-details-marker {{ display:none; }} summary::after {{ content:'⌄'; margin-left:auto; color:var(--muted); font-size:20px; }} details[open] summary::after {{ transform:rotate(180deg); }} .case-content {{ margin-top:18px; border-top:1px solid var(--line); padding-top:18px; }}
    .score-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:9px; margin:16px 0; }} .score {{ padding:10px; border-radius:10px; background:#f4f8f6; }} .score b {{ display:block; font-size:18px; }} .score span {{ color:var(--muted); font-size:12px; }} .check {{ padding:10px 0; border-top:1px solid var(--line); }} .check:first-child {{ border-top:0; }} .check-name {{ font-weight:700; }} .check.pass .status {{ color:var(--pass); }} .check.fail .status {{ color:var(--fail); }} .evidence {{ margin-top:10px; padding:13px; border-left:3px solid #5e9788; background:#f4f8f6; }} .evidence p {{ margin:6px 0 0; }}
    .empty {{ color:var(--muted); font-style:italic; }} @media (max-width:720px) {{ .page {{ padding:18px 13px 32px; }} .hero,section,.audit-case {{ padding:18px; }} .cards {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .score-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
  </style>
</head>
<body><div class="page">{body}</div></body>
</html>""",
            encoding="utf-8",
        )

    issue_list = "".join(
        f"<li><strong>{safe(category)}</strong> — {count} case(s) <span class=\"action\">· {safe(actions.get(category, 'Analyse the contract and add a regression test.'))}</span></li>"
        for category, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))
    ) or '<p class="empty">No categorised issue.</p>'
    summary_rows = "".join(
        f"<tr><td>{safe(item.test_id)}</td><td>{verdict_badge(item.verdict)}</td><td>{safe(item.failure_category.value if item.failure_category else None)}</td></tr>"
        for item in report.tests
    ) or '<tr><td colspan="3" class="empty">No scenario was run.</td></tr>'
    summary_body = f"""
<header class="hero"><p class="eyebrow">MyFinance · Test Lab</p><h1>Campaign summary</h1><p class="subtitle">{safe(report.run_id)}</p><p class="meta">Run from {safe(report.started_at.isoformat())} to {safe(report.finished_at.isoformat())}</p></header>
<main><div class="cards"><div class="card"><span class="number">{len(report.tests)}</span><span class="label">Scenarios run</span></div><div class="card pass"><span class="number">{counts[Verdict.PASS]}</span><span class="label">Passed</span></div><div class="card fail"><span class="number">{counts[Verdict.FAIL]}</span><span class="label">Issues detected</span></div><div class="card inconclusive"><span class="number">{counts[Verdict.INCONCLUSIVE]}</span><span class="label">To confirm</span></div></div>
<section><h2>Fix priorities</h2><ul>{issue_list}</ul></section>
<section><h2>Results by scenario</h2><div class="table-wrap"><table><thead><tr><th>Scenario</th><th>Verdict</th><th>Category</th></tr></thead><tbody>{summary_rows}</tbody></table></div></section>
<p class="meta">{report.groq_call_count} Groq call(s). The detailed audit contains checks and evidence for every scenario.</p></main>"""

    score_labels = (("Relevance", "relevance"), ("Factuality", "factuality"), ("Source fidelity", "source_fidelity"), ("Coherence", "conversation_coherence"), ("Year", "year_respect"), ("Unit", "unit_respect"), ("Clarity", "clarity"), ("Format", "format_respect"))
    audit_cases: list[str] = []
    for item in report.tests:
        checks = "".join(
            f'<div class="check {"pass" if check.passed else "fail"}"><span class="status">{"✓" if check.passed else "✗"}</span> <span class="check-name">{safe(check.name)}</span><br><span class="meta">Expected: {safe(check.expected)} · Actual: {safe(check.actual)}{f" · {safe(check.detail)}" if check.detail else ""}</span></div>'
            for check in item.deterministic_checks
        ) or '<p class="empty">No deterministic check recorded.</p>'
        evidence = "".join(
            f'<div class="evidence"><strong>{safe(proof.source_path)} · page {safe(proof.page_number)}</strong><p>{safe(" ".join(proof.excerpt.split())[:500])}</p></div>'
            for proof in item.evidence
        ) or '<p class="empty">No source evidence is associated with this scenario.</p>'
        scores = "".join(
            f'<div class="score"><b>{safe(getattr(item, field))}/5</b><span>{label}</span></div>'
            for label, field in score_labels
        )
        category = item.failure_category.value if item.failure_category else None
        audit_cases.append(
            f"""<details class="audit-case {item.verdict.value}"{' open' if item.verdict is Verdict.FAIL else ''}>
<summary><span>{verdict_badge(item.verdict)}</span><h3>{safe(item.test_id)}</h3><span class="meta">{safe(category)}</span></summary>
<div class="case-content"><p><strong>Conclusion:</strong> {safe(item.rationale)}</p>{f'<p><strong>Probable cause:</strong> {safe(item.probable_cause)}</p>' if item.probable_cause else ''}<div class="score-grid">{scores}</div><h3>Deterministic checks</h3>{checks}<h3 style="margin-top:18px">Evidence</h3>{evidence}</div></details>"""
        )
    audit_body = f"""
<header class="hero"><p class="eyebrow">MyFinance · Test Lab</p><h1>Detailed audit</h1><p class="subtitle">{safe(report.run_id)}</p><p class="meta">{len(report.tests)} scenarios · {counts[Verdict.PASS]} passed · {counts[Verdict.FAIL]} issues · {counts[Verdict.INCONCLUSIVE]} to confirm</p></header>
<main><p class="meta">Open each scenario to review the evaluation, deterministic checks and evidence excerpts. Failed scenarios are open by default.</p>{''.join(audit_cases) or '<section><p class="empty">No scenario was run.</p></section>'}</main>"""

    write_html(summary_html_path, f"Summary — {report.run_id}", summary_body)
    write_html(audit_html_path, f"Detailed audit — {report.run_id}", audit_body)
    return json_path, summary_markdown_path, summary_html_path, audit_markdown_path, audit_html_path
