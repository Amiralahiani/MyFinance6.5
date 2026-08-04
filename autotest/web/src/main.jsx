import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API = import.meta.env.VITE_TESTING_API_URL ?? "http://localhost:8001";
const CHAT_WEB = import.meta.env.VITE_CHAT_WEB_URL ?? "http://localhost:3000";
const campaignEventTypes = ["campaign_created", "stage_update", "agent_output", "execution_completed", "scenario_completed", "campaign_completed", "technical_error"];
const stages = [
  ["generator", "Generator", "Builds the catalogue from validated reports and facts."],
  ["planner", "Planner", "Applies channel policy and selects scenarios."],
  ["executor", "Executor", "Queries the API and, where relevant, the Web interface."],
  ["evaluator", "Evaluator", "Compares responses with automatically validated facts and PDF evidence."],
  ["critic", "Critic", "Reviews results with Groq when the key is available."],
  ["reporter", "Reporter", "Produces JSON, Markdown and HTML reports."],
];

const campaignIdFromUrl = () => {
  const segment = location.pathname.match(/^\/campaigns\/([^/]+)/)?.[1] ?? null;
  return segment === "history" ? null : segment;
};
const historyFromUrl = () => location.pathname === "/campaigns/history";
const statusLabel = (status) => ({ pending: "Pending", waiting: "Waiting", starting: "Starting", running: "Running", completed: "Completed", completed_with_fallback: "Completed with fallback", fallback_local: "Local policy", pass: "Passed", passed: "Passed", fail: "Issue detected", failed: "Issue detected", warning: "Review needed", rejected: "Rejected by guardrails", duplicate: "Too close to a previous question", provider_error: "Groq rejected the request", invalid_output: "Invalid AI response", budget_exhausted: "Local limit reached", inconclusive: "To confirm", technical_error: "Technical error", skipped: "Not run" }[status] ?? "Unavailable");
const formatDate = (value) => value ? new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";
const metricLabels = {
  customer_deposits: "Customer deposits and balances",
  customer_loans_net: "Customer loans",
  net_banking_income: "Net banking income (NBI)",
  net_income: "Net income",
  total_assets: "Total assets",
  total_liabilities: "Total liabilities",
  total_equity: "Equity",
};

const formatValue = (value) => value === undefined || value === null || value === "" ? "—" : new Intl.NumberFormat("en-US").format(Number(value));
const formatScale = (scale, currency) => scale === "thousand" ? `thousand ${currency ?? "TND"}` : currency ?? "—";

function Status({ value }) { return <span className={`status ${value ?? "pending"}`}>{statusLabel(value)}</span>; }

function App() {
  const [campaigns, setCampaigns] = useState([]);
  const [webCoverage, setWebCoverage] = useState(null);
  const [visualCheck, setVisualCheck] = useState(null);
  const [currentId, setCurrentId] = useState(campaignIdFromUrl());
  const [showHistory, setShowHistory] = useState(historyFromUrl());
  const [current, setCurrent] = useState(null);
  const [selectedStage, setSelectedStage] = useState("generator");
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  const load = async () => {
    try {
      const [campaignsResponse, coverageResponse, visualCheckResponse] = await Promise.all([
        fetch(`${API}/api/campaigns`), fetch(`${API}/api/coverage/web`), fetch(`${API}/api/visual-checks/latest`),
      ]);
      if (!campaignsResponse.ok) throw new Error();
      setCampaigns((await campaignsResponse.json()).campaigns ?? []);
      if (coverageResponse.ok) setWebCoverage(await coverageResponse.json());
      if (visualCheckResponse.ok) setVisualCheck((await visualCheckResponse.json()).visual_check ?? null);
      setError("");
    } catch { setError("The Testing service is unavailable. Start the API on port 8001."); }
  };
  const refreshCurrent = async () => {
    if (!currentId) return;
    const response = await fetch(`${API}/api/campaigns/${currentId}`);
    if (response.ok) setCurrent(await response.json());
  };
  const go = (id = null, page = "campaigns") => {
    history.pushState({}, "", id ? `/campaigns/${id}` : page === "history" ? "/campaigns/history" : "/campaigns");
    setCurrentId(id);
    setShowHistory(!id && page === "history");
    setSelectedStage("generator");
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!currentId && location.pathname !== (showHistory ? "/campaigns/history" : "/campaigns")) {
      history.replaceState({}, "", showHistory ? "/campaigns/history" : "/campaigns");
    }
  }, [currentId, showHistory]);
  useEffect(() => {
    const syncRoute = () => {
      setCurrentId(campaignIdFromUrl());
      setShowHistory(historyFromUrl());
      setSelectedStage("generator");
    };
    addEventListener("popstate", syncRoute);
    return () => removeEventListener("popstate", syncRoute);
  }, []);
  useEffect(() => {
    if (!currentId) { setCurrent(null); return undefined; }
    let alive = true;
    const update = async () => { if (alive) await refreshCurrent(); };
    update();
    const source = new EventSource(`${API}/api/campaigns/${currentId}/events`);
    const receive = () => { update(); load(); };
    campaignEventTypes.forEach((type) => source.addEventListener(type, receive));
    source.onerror = () => source.close();
    return () => { alive = false; source.close(); };
  }, [currentId]);
  useEffect(() => {
    const visualCheckId = visualCheck?.id;
    if (!visualCheckId || !["pending", "running"].includes(visualCheck.status)) return undefined;
    const source = new EventSource(`${API}/api/visual-checks/${visualCheckId}/events`);
    const receive = () => { load(); };
    ["visual_created", "visual_started", "visual_output", "visual_completed"].forEach((type) => source.addEventListener(type, receive));
    source.onerror = () => source.close();
    return () => source.close();
  }, [visualCheck?.id, visualCheck?.status]);

  async function startCampaign(profile = "catalog") {
    if (starting) return;
    setStarting(true); setError("");
    try {
      const response = await fetch(`${API}/api/campaigns/catalog`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ include_web: profile !== "exploration", with_groq: true, scenario_profile: profile }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Unable to start the campaign.");
      await load(); go(payload.id);
    } catch (reason) { setError(reason.message ?? "Unable to start the campaign."); }
    finally { setStarting(false); }
  }

  async function startVisualCheck() {
    if (["pending", "running"].includes(visualCheck?.status)) return;
    setError("");
    try {
      const response = await fetch(`${API}/api/visual-checks`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Unable to start the visual check.");
      await load();
    } catch (reason) { setError(reason.message ?? "Unable to start the visual check."); }
  }

  const latestCompleted = campaigns.find((campaign) => campaign.status === "completed");
  const latestExploration = campaigns.find((campaign) => campaign.status === "completed" && campaign.configuration?.scenario_profile === "exploration");
  const runningCampaign = campaigns.find((campaign) => ["pending", "starting", "running"].includes(campaign.status));
  const latestSummary = latestExploration?.result?.summary ?? {};
  const metrics = useMemo(() => ({
    total: latestSummary.total ?? 0,
    completedTotal: latestSummary.total ?? 0,
    passed: latestSummary.pass ?? 0,
    issues: (latestSummary.fail ?? 0) + (latestSummary.warning ?? 0),
    inconclusive: latestSummary.inconclusive ?? 0,
  }), [latestSummary]);

  return <main className="testing-app">
    <aside className="sidebar">
      <a className="brand" href="/campaigns" onClick={(event) => { event.preventDefault(); go(); }}><span>MF</span><b>AUTONOMOUS<br />TESTING</b></a>
      <p className="product-label">MYFINANCE · TEST LAB</p>
      <nav aria-label="Testing navigation">
        <button className={!currentId && !showHistory ? "selected" : ""} onClick={() => go()}><i>▦</i> Campaigns</button>
        <button className={showHistory ? "selected" : ""} onClick={() => go(null, "history")}><i>◫</i> History <em>{campaigns.length}</em></button>
      </nav>
      <div className="sidebar-footer"><span><b /> CHAT API</span><small>127.0.0.1:8000</small><a href={CHAT_WEB}>← Back to Chat</a></div>
    </aside>
    <section className="workspace">
      <header className="topbar"><div><span>AUTONOMOUS VALIDATION</span><strong>{currentId ? "Campaign detail" : showHistory ? "Campaign history" : "Reproducible campaigns"}</strong></div><div className="live"><i /> SERVICE {error ? "CHECK REQUIRED" : "READY"}</div></header>
      {error && <div className="notice"><b>Connection required.</b> {error}</div>}
      {currentId ? <CampaignDetail campaign={current} selectedStage={selectedStage} selectStage={setSelectedStage} onBack={() => go(null, "history")} /> : showHistory ? <CampaignHistory campaigns={campaigns} open={go} /> : <Dashboard coverage={webCoverage} visualCheck={visualCheck} metrics={metrics} runningCampaign={runningCampaign} starting={starting} startCampaign={startCampaign} startVisualCheck={startVisualCheck} open={go} />}
    </section>
  </main>;
}

function Dashboard({ coverage, visualCheck, metrics, runningCampaign, starting, startCampaign, startVisualCheck, open }) {
  const coverageSummary = coverage?.summary;
  const visualRunning = ["pending", "running"].includes(visualCheck?.status);
  const visualProgress = visualCheck?.result?.progress ?? {};
  const visualLogs = (visualCheck?.events ?? []).filter((event) => event.type === "visual_output").slice(-12);
  const visibleCoverage = visualCheck?.result?.coverage ?? coverage;
  const visibleSummary = visibleCoverage?.summary;
  return <div className="page"><section className="intro"><p className="eyebrow">AI ISSUE EXPLORATION</p><h1>Do not confirm.<br /><em>Find what breaks.</em></h1><p>This campaign asks Groq to create new questions targeting hallucinations, ambiguity, bypass attempts and loss of context.</p></section>
    <section className="metrics"><Metric label="Risk intents" value="12" /><Metric label="Latest AI scenarios" value={metrics.total || "—"} /><Metric label="Issues detected" value={metrics.issues || "—"} kind={metrics.issues ? "issue" : ""} /><Metric label="Cases to investigate" value={metrics.inconclusive || "—"} /></section>
    {runningCampaign && <section className="running-campaign"><div><span>RUNNING</span><h2>Automated validation is running.</h2><p>This campaign is testing the prepared questions. The final result will appear when it is complete.</p></div><button className="catalog-link" onClick={() => open(runningCampaign.id)}>View progress</button></section>}
    <section className="campaign-launch"><div><span className="step-number">EXPLORATORY CAMPAIGN</span><h2>Generate, then challenge the Chat</h2><p>Groq formulates 12 new questions from our risk intents. The system runs them against the real API, checks safety rules and retains every anomaly found.</p><small>This campaign requires a Groq key configured in the Testing service.</small></div><div className="launch-actions"><button className="primary launch" disabled={starting} onClick={() => startCampaign("exploration")}>{starting ? "Generating…" : "Start AI exploration"} <b>↗</b></button></div></section>
    <section className={`web-campaign ${!visualRunning && visibleCoverage?.available && visibleSummary.failed === 0 ? "pass" : ""}`}><div><span>CHAT VISUAL CHECK · PLAYWRIGHT</span><h2>{visualRunning ? `Visual check in progress — ${visualProgress.completed ?? 0} / ${visualProgress.total ?? "?"}` : visibleCoverage?.available ? `${visibleSummary.passed} / ${visibleSummary.total} Chat interface journeys passed` : "No visual check available"}</h2><p>{visualRunning ? "The automated browser is checking the Chat live. Logs and counters update here." : visibleCoverage?.available ? `Last run: ${formatDate(visibleCoverage.generated_at)}. This test remains separate from a Groq campaign.` : "Start the first visual check from this page."}</p>{visualRunning && <><div className="visual-progress"><i style={{ width: `${visualProgress.total ? Math.round((visualProgress.completed ?? 0) / visualProgress.total * 100) : 8}%` }} /></div><details className="visual-log" open><summary>Live log</summary><pre>{visualLogs.map((event) => event.line).join("\n") || "Starting Playwright…"}</pre></details></>}</div><div className="web-campaign-mark"><b>{visualRunning ? "RUNNING" : visualCheck?.status === "failed" || visualCheck?.status === "technical_error" ? "FAILED" : visibleCoverage?.available && visibleSummary.failed === 0 ? "PASS" : "PENDING"}</b><small>Interface test</small><button className="primary visual-launch" disabled={visualRunning} onClick={startVisualCheck}>{visualRunning ? "Running…" : "Start check"}</button></div></section>
  </div>;
}

function Metric({ label, value, kind = "" }) { const details = { "Risk intents": "local safety contracts", "Latest AI scenarios": "generated, not handwritten", "Issues detected": "failures or warnings", "Cases to investigate": "insufficient evidence" }; return <article className={`metric ${kind}`}><span>{label}</span><strong>{value}</strong><small>{details[label] ?? "—"}</small></article>; }

function CampaignList({ campaigns, open }) {
  if (!campaigns.length) return <div className="empty-state">No campaign has been started yet. AI exploration is ready once Groq is configured.</div>;
  const labelFor = (campaign) => campaign.configuration?.scenario_profile === "exploration" ? "AI issue exploration" : campaign.configuration?.scenario_profile === "behavior" ? "Conversational behaviour" : campaign.configuration?.trigger === "diagnostic" ? "Technical diagnostic" : "Reference catalogue";
  return <div className="scenario-table"><div className="table-head"><span>CAMPAIGN</span><span>SCENARIOS</span><span>API + WEB</span><span>STATUS</span><span>STARTED</span></div>{campaigns.map((campaign) => <button className="scenario-row" key={campaign.id} onClick={() => open(campaign.id)}><div><b>{campaign.id}</b><small>{labelFor(campaign)}</small></div><span>{campaign.result?.summary?.total ?? "—"}</span><span>{campaign.configuration?.include_web ? "Yes" : "API"}</span><Status value={campaign.status} /><time>{formatDate(campaign.created_at)}</time></button>)}</div>;
}

function CampaignHistory({ campaigns, open }) {
  return <div className="page"><section className="intro"><p className="eyebrow">CAMPAIGN HISTORY</p><h1>Review.<br /><em>Understand.</em></h1><p>Select a campaign to view its scenarios, decisions and reports.</p></section><CampaignList campaigns={campaigns} open={open} /></div>;
}

function CampaignDetail({ campaign, selectedStage, selectStage, onBack }) {
  const events = campaign?.events ?? [];
  const stageEvent = (stage) => [...events].reverse().find((event) => event.stage === stage && event.type === "stage_update");
  const scenarioEvents = events.filter((event) => event.type === "scenario_completed");
  const executionEvents = events.filter((event) => event.type === "execution_completed");
  const hasConfirmationPass = Boolean(
    stageEvent("critic")?.confirmation_requested
    || events.some((event) => ["planner_confirmation", "executor_confirmation", "evaluator_confirmation"].includes(event.stage) && event.status !== "skipped")
    || scenarioEvents.some((event) => event.critic?.next_action_required),
  );
  const primaryStages = [
    ["generator", "AI Generator", "Creates new questions from the risk intents."],
    ["planner", "AI Planner", "Only authorises a safe message to the local Chat API."],
    ["executor", "Executor · initial pass", "Queries the Chat with only the questions accepted by the Planner."],
    ["evaluator", "Evaluator · initial pass", "Compares responses with the safety contracts and available evidence."],
    ["critic", "AI Critic", "Decides whether a confirmation pass is genuinely needed."],
  ];
  const confirmationStages = [
    ["planner_confirmation", "AI Planner · confirmation", "Authorises the additional questions requested by the Critic."],
    ["executor_confirmation", "Executor · confirmation", "Queries the Chat only on points to confirm."],
    ["evaluator_confirmation", "Evaluator · confirmation", "Evaluates the additional responses."],
  ];
  const explorationStages = [
    ...primaryStages,
    ...(hasConfirmationPass ? confirmationStages : []),
    stages[5],
  ];
  const activeStages = campaign?.configuration?.scenario_profile === "exploration" ? explorationStages : stages;
  const resolvedSelectedStage = activeStages.some(([key]) => key === selectedStage) ? selectedStage : activeStages[0][0];
  const selected = activeStages.find(([key]) => key === resolvedSelectedStage) ?? activeStages[0];
  const data = stageEvent(resolvedSelectedStage);
  const scenariosForStage = (stage) => {
    const records = stage.startsWith("executor") && executionEvents.length ? executionEvents : scenarioEvents;
    if (stage === "critic") return scenarioEvents;
    if (stage.endsWith("_confirmation")) return records.filter((event) => event.passage === "confirmation");
    return records.filter((event) => event.passage !== "confirmation");
  };
  const stageScenarios = scenariosForStage(resolvedSelectedStage);
  const terminal = ["completed", "technical_error"].includes(campaign?.status);
  return <div className="page detail-page"><button className="back" onClick={onBack}>← Back to campaigns</button><div className="detail-head"><div><p className="eyebrow">{campaign?.id ?? "Campaign"}</p><h1>The validation loop</h1><p>{campaign?.configuration?.include_web ? "API and Web interface are included in this campaign." : "This campaign is limited to the API."}</p></div><Status value={campaign?.status} /></div>
    <section className="flow interactive-flow"><div className="flow-title"><span>RUNNABLE AND REVIEWABLE STAGES</span><small>The confirmation pass appears only when requested by the Critic.</small></div>{activeStages.map(([key, name, description], index) => { const event = stageEvent(key); const hasLiveResult = (key === "evaluator" || key === "evaluator_confirmation") && scenariosForStage(key).length > 0; const status = event?.status ?? (hasLiveResult ? "running" : campaign?.status === "pending" ? "pending" : "waiting"); const progress = event?.completed !== undefined && event?.total ? ` · ${event.completed} / ${event.total}` : ""; return <button type="button" className={`flow-step ${event || hasLiveResult ? "done" : ""} ${resolvedSelectedStage === key ? "active" : ""}`} onClick={() => selectStage(key)} key={key}><b>{String(index + 1).padStart(2, "0")}</b><strong>{name}</strong><small>{description}{progress}</small><Status value={status} /></button>; })}</section>
    <section className="stage-panel"><div className="stage-panel-heading"><div><span>AGENT · {selected[1].toUpperCase()}</span><h2>Role: {selected[2]}</h2></div><Status value={data?.status ?? (terminal ? "skipped" : "pending")} /></div><StageEvidence stage={resolvedSelectedStage} data={data} scenarios={stageScenarios} campaign={campaign} /></section>
  </div>;
}

function ObservedResponse({ execution }) {
  const api = execution?.api;
  const web = execution?.web;
  const response = api?.response;
  if (response?.type === "numeric") return <div className="observed-result">
    <span className="observed-label">RESPONSE RECEIVED</span>
    <strong className="observed-value">{formatValue(response.value)}</strong>
    <span className="observed-unit">{metricLabels[response.metric_id] ?? response.metric_id} · {formatScale(response.unit_scale, response.currency)} · financial year {response.reporting_year}</span>
    <dl className="observed-metadata">
      <div><dt>Source</dt><dd>{response.source_document?.split("/").pop() ?? "—"}</dd></div>
      <div><dt>Page</dt><dd>{response.page_number ?? "—"}</dd></div>
    </dl>
    {response.source_excerpt && <blockquote>{response.source_excerpt}</blockquote>}
  </div>;
  if (response?.type === "document") return <div className="observed-result">
    <span className="observed-label">DOCUMENTARY RESPONSE RECEIVED</span>
    <p>{response.analysis?.direct_answer ?? response.answer ?? response.message ?? "Documentary response received."}</p>
    {response.evidence?.length > 0 && <ul>{response.evidence.slice(0, 3).map((item, index) => <li key={index}>{item.source_document?.split("/").pop() ?? "Official report"}{item.page_number ? ` · p. ${item.page_number}` : ""}</li>)}</ul>}
  </div>;
  if (response) return <div className="observed-result">
    <span className="observed-label">RESPONSE RECEIVED</span>
    <p>{response.message ?? response.answer ?? "Response received."}</p>
  </div>;
  if (web) return <div className="observed-result"><span className="observed-label">RESPONSE VISIBLE ON THE WEB</span><p>{web.visible_text ?? "Web response received."}</p></div>;
  return <p>The response was not retained for this older campaign.</p>;
}

function ValidationExplanation({ scenario }) {
  if (scenario.category === "cross_channel") return <p className="validation-explanation"><b>Validation:</b> the same question is sent to the API and Web interface; type, value, year and source must be identical.</p>;
  if (scenario.category === "conversation" || scenario.scenario_id?.startsWith("BEHAVIOR")) return <p className="validation-explanation"><b>Validation:</b> the behavioural contract is checked: correct response category, no invented value, and the expected message or evidence.</p>;
  if (scenario.scenario_id?.startsWith("MISSING")) return <p className="validation-explanation"><b>Validation:</b> no numerical data may be invented when no automatically validated fact exists.</p>;
  return <p className="validation-explanation"><b>Validation:</b> strict comparison with the automatically validated fact: bank, metric, financial year, value, unit, document, page and PDF excerpt.</p>;
}

function EvaluatorDetails({ scenario }) {
  const detail = scenario.evaluator;
  const failedChecks = detail?.deterministic_checks?.filter((check) => check.passed === false) ?? [];
  const provider = detail?.provider;
  return <><ValidationExplanation scenario={scenario} /><p><b>Control scores:</b> relevance {scenario.scores?.relevance}/5 · factuality {scenario.scores?.factuality}/5 · source fidelity {scenario.scores?.source_fidelity}/5 · coherence {scenario.scores?.coherence}/5</p>{detail?.rationale && <p><b>Evaluator conclusion:</b> {detail.rationale}</p>}{provider?.status === "failed" && <p><b>Groq evaluation unavailable:</b> {provider.error ?? "unspecified error"}</p>}{detail?.probable_cause && <p><b>Probable cause:</b> {detail.probable_cause}</p>}{failedChecks.length > 0 && <p><b>Failed rules:</b> {failedChecks.map((check) => check.name).join(" · ")}</p>}</>;
}

function StageEvidence({ stage, data, scenarios, campaign }) {
  if (stage === "generator" || stage === "planner" || stage === "planner_confirmation") {
    const outputs = (campaign?.events ?? []).filter((event) => event.type === "agent_output" && event.stage === stage);
    const accepted = outputs.filter((output) => ["completed", "fallback_local"].includes(output.status)).length;
    const rejected = outputs.length - accepted;
    const firstStageUpdate = (campaign?.events ?? []).find((event) => event.type === "stage_update" && event.stage === stage);
    const targetCount = data?.target_scenarios ?? data?.risk_charters ?? firstStageUpdate?.target_scenarios ?? firstStageUpdate?.risk_charters;
    const replacementAttempts = data?.replacement_attempts ?? Math.max(0, outputs.length - (targetCount ?? outputs.length));
    const targetReached = data?.target_reached ?? accepted >= targetCount;
    const outputStatus = (output) => {
      const error = output.provider?.error ?? "";
      if (error.startsWith("Groq request failed:")) return "provider_error";
      if (error.startsWith("Invalid structured Groq response:")) return "invalid_output";
      if (error.toLowerCase().includes("budget")) return "budget_exhausted";
      return output.status;
    };
    const providerErrors = outputs.filter((output) => outputStatus(output) === "provider_error").length;
    const invalidOutputs = outputs.filter((output) => outputStatus(output) === "invalid_output").length;
    if (outputs.length) return <>{data?.reason && <p className="stage-copy"><b>Stop reason:</b> {data.reason}</p>}<p className="stage-copy">{stage === "generator" ? providerErrors ? `${outputs.length} Groq attempt(s) for ${targetCount ?? "—"} target(s): ${accepted} question(s) generated, then the campaign was interrupted by Groq. This is not a guardrail rejection.` : invalidOutputs ? `${outputs.length} attempt(s) for ${targetCount ?? "—"} target(s): ${invalidOutputs} invalid AI response(s) rejected by the local validator before any execution.` : targetReached ? `${outputs.length} attempt(s), including ${replacementAttempts} replacement(s), to reach the target of ${targetCount} safe scenarios: ${accepted} new question(s) and ${rejected} rejected by guardrails.` : `${outputs.length} attempt(s), including ${replacementAttempts} replacement(s), for the target of ${targetCount ?? "—"} scenarios: ${accepted} new question(s) and ${rejected} rejected by guardrails. The target has not yet been reached.` : `${outputs.length} action(s) reviewed: ${accepted} authorised, ${rejected} rejected. The Planner may authorise only a message to the local Chat API.`}</p><div className="evaluation-list">{outputs.map((output) => <article key={output.id}><div><b>{output.question ?? output.charter ?? output.scenario_id}</b><small>{output.scenario_id ?? output.charter ?? "—"} · model {output.provider?.model ?? "—"}</small></div><Status value={outputStatus(output)} /><span>{output.provider?.status === "success" ? "Valid JSON" : output.provider?.error ?? "—"}</span></article>)}</div></>;
  }
  if (stage === "critic") {
    const reviewed = scenarios.filter((scenario) => scenario.critic);
    if (reviewed.length) return <><p className="stage-copy">The Critic rereads anomalies. It can request a confirmation question and create a regression test when an issue is confirmed.</p><div className="evaluation-list">{reviewed.map((scenario) => <article key={scenario.id}><div><b>{scenario.question ?? scenario.title}</b><small>{scenario.scenario_id} · confidence {Math.round((scenario.critic?.confidence ?? 0) * 100)} %</small><details className="observed-answer"><summary>View the Critic’s decision</summary><p><b>Decision:</b> {scenario.critic?.reason ?? "—"}</p>{scenario.critic?.provider?.status === "failed" && <p><b>Groq Critic unavailable:</b> {scenario.critic.provider.error ?? "unspecified error"}</p>}{scenario.critic?.follow_up_question && <p><b>Confirmation question:</b> {scenario.critic.follow_up_question}</p>}{scenario.regression && <p><b>Regression:</b> {scenario.regression.created ? "created" : "already known"} · {scenario.regression.regression_id}</p>}</details></div><Status value={scenario.verdict} /><span>{scenario.critic?.create_regression_test ? "regression candidate" : scenario.critic?.next_action_required ? "confirmation requested" : "no action"}</span></article>)}</div></>;
  }
  if (["evaluator", "executor", "evaluator_confirmation", "executor_confirmation"].includes(stage)) { const isExecutor = stage.startsWith("executor"); return <><p className="stage-copy">{scenarios.length ? (isExecutor ? `${scenarios.length} Chat response(s) received immediately. Quality evaluation continues separately.` : `${scenarios.length} business verdict(s) received. Open a row to see the rules, cause and conclusion.`) : "Results will appear here while the stage is running."}</p>{scenarios.length > 0 && <div className="evaluation-list">{scenarios.map((scenario) => <article key={scenario.id}><div><b>{scenario.index} / {scenario.total} · {scenario.question ?? scenario.title}</b><small>{scenario.scenario_id} · {isExecutor ? `API HTTP ${scenario.execution?.api?.http_status ?? "—"} · ${scenario.execution?.api?.latency_ms ?? "—"} ms${scenario.execution?.web ? ` · Web ${scenario.execution.web.latency_ms} ms` : ""}` : scenario.channels?.join(" + ")}</small><details className="observed-answer"><summary>{isExecutor ? "View observed response and evidence" : "View validation details"}</summary><p><b>Question:</b> {scenario.question ?? scenario.title}</p>{isExecutor ? <ObservedResponse execution={scenario.execution} /> : <EvaluatorDetails scenario={scenario} />}</details></div><Status value={isExecutor ? (scenario.execution?.api?.errors?.length ? "failed" : "completed") : scenario.verdict} /><span>{isExecutor ? scenario.execution?.api?.response_type ?? scenario.execution?.web?.response_type ?? "response unavailable" : scenario.failure_category ?? "checks passed"}</span></article>)}</div>}</>; }
  if (stage === "reporter" && campaign?.result?.report_paths) {
    const summary = campaign.result.summary ?? {};
    const labels = {
      summary_html: "Open summary",
      audit_html: "Open detailed audit",
    };
    const availableFormats = Object.keys(labels).filter((format) => campaign.result.report_paths[format] || campaign.result.report_paths.json);
    return <><p className="stage-copy">Choose the summary for a quick overview or the audit to examine every scenario.</p><section className="report-summary"><div><span>SCENARIOS</span><strong>{summary.total ?? "—"}</strong></div><div><span>PASSED</span><strong>{summary.pass ?? 0}</strong></div><div><span>ISSUES</span><strong>{summary.fail ?? 0}</strong></div><div><span>TO CONFIRM</span><strong>{summary.inconclusive ?? 0}</strong></div></section><div className="report-actions">{availableFormats.map((format) => <a key={format} href={`${API}/api/campaigns/${campaign.id}/reports/${format}`} target="_blank" rel="noreferrer" className="primary">{labels[format]} <b>↗</b></a>)}</div></>;
  }
  if (!data) return <p className="stage-copy">This stage has not produced data yet.</p>;
  return <dl className="evidence-list">{Object.entries(data).filter(([key]) => !["id", "created_at", "type", "stage"].includes(key)).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "—")}</dd></div>)}</dl>;
}

createRoot(document.getElementById("root")).render(<App />);
