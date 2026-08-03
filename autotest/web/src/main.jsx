import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API = import.meta.env.VITE_TESTING_API_URL ?? "http://localhost:8001";
const CHAT_WEB = import.meta.env.VITE_CHAT_WEB_URL ?? "http://localhost:3000";
const campaignEventTypes = ["campaign_created", "stage_update", "agent_output", "execution_completed", "scenario_completed", "campaign_completed", "technical_error"];
const stages = [
  ["generator", "Générateur", "Construit le catalogue à partir des rapports et faits validés."],
  ["planner", "Planificateur", "Applique la politique de canaux et sélectionne les scénarios."],
  ["executor", "Executor", "Interroge l’API et, pour les cas concernés, l’interface Web."],
  ["evaluator", "Evaluator", "Compare les réponses aux faits et preuves PDF auto-validés."],
  ["critic", "Critic", "Revoit les résultats avec Groq quand la clé est disponible."],
  ["reporter", "Reporter", "Produit les rapports JSON, Markdown et HTML."],
];

const campaignIdFromUrl = () => {
  const segment = location.pathname.match(/^\/campaigns\/([^/]+)/)?.[1] ?? null;
  return segment === "history" ? null : segment;
};
const historyFromUrl = () => location.pathname === "/campaigns/history";
const statusLabel = (status) => ({ pending: "En attente", waiting: "En attente", starting: "Démarrage", running: "En cours", completed: "Terminé", fallback_local: "Politique locale", pass: "Validé", passed: "Validé", fail: "Faille détectée", failed: "Faille détectée", warning: "À examiner", rejected: "Rejeté par garde-fou", duplicate: "Trop proche d’une question passée", provider_error: "Groq a refusé la requête", invalid_output: "Réponse IA invalide", budget_exhausted: "Limite locale atteinte", inconclusive: "À confirmer", technical_error: "Erreur technique", skipped: "Non exécuté" }[status] ?? "Non disponible");
const formatDate = (value) => value ? new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";
const metricLabels = {
  customer_deposits: "Dépôts et avoirs de la clientèle",
  customer_loans_net: "Créances sur la clientèle",
  net_banking_income: "Produit net bancaire (PNB)",
  net_income: "Résultat net",
  total_assets: "Total des actifs",
  total_liabilities: "Total des passifs",
  total_equity: "Capitaux propres",
};

const formatValue = (value) => value === undefined || value === null || value === "" ? "—" : new Intl.NumberFormat("fr-FR").format(Number(value));
const formatScale = (scale, currency) => scale === "thousand" ? `en milliers de ${currency ?? "TND"}` : currency ?? "—";

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
    } catch { setError("Le service Testing est indisponible. Démarrez l’API sur le port 8001."); }
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
      if (!response.ok) throw new Error(payload.detail ?? "Impossible de démarrer la campagne.");
      await load(); go(payload.id);
    } catch (reason) { setError(reason.message ?? "Impossible de démarrer la campagne."); }
    finally { setStarting(false); }
  }

  async function startVisualCheck() {
    if (["pending", "running"].includes(visualCheck?.status)) return;
    setError("");
    try {
      const response = await fetch(`${API}/api/visual-checks`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Impossible de démarrer le contrôle visuel.");
      await load();
    } catch (reason) { setError(reason.message ?? "Impossible de démarrer le contrôle visuel."); }
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
      <nav aria-label="Navigation Testing">
        <button className={!currentId && !showHistory ? "selected" : ""} onClick={() => go()}><i>▦</i> Campagnes</button>
        <button className={showHistory ? "selected" : ""} onClick={() => go(null, "history")}><i>◫</i> Historique <em>{campaigns.length}</em></button>
      </nav>
      <div className="sidebar-footer"><span><b /> CHAT API</span><small>127.0.0.1:8000</small><a href={CHAT_WEB}>← Retour au Chat</a></div>
    </aside>
    <section className="workspace">
      <header className="topbar"><div><span>VALIDATION AUTONOME</span><strong>{currentId ? "Détail de la campagne" : showHistory ? "Historique des campagnes" : "Campagnes reproductibles"}</strong></div><div className="live"><i /> SERVICE {error ? "À VÉRIFIER" : "PRÊT"}</div></header>
      {error && <div className="notice"><b>Connexion requise.</b> {error}</div>}
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
  return <div className="page"><section className="intro"><p className="eyebrow">EXPLORATION IA DES FAILLES</p><h1>Ne pas confirmer.<br /><em>Chercher ce qui casse.</em></h1><p>Cette campagne demande à Groq de créer de nouvelles questions visant les hallucinations, ambiguïtés, contournements et pertes de contexte.</p></section>
    <section className="metrics"><Metric label="Intentions de risque" value="12" /><Metric label="Derniers scénarios IA" value={metrics.total || "—"} /><Metric label="Failles détectées" value={metrics.issues || "—"} kind={metrics.issues ? "issue" : ""} /><Metric label="Cas à investiguer" value={metrics.inconclusive || "—"} /></section>
    {runningCampaign && <section className="running-campaign"><div><span>EXÉCUTION EN COURS</span><h2>La vérification automatique tourne.</h2><p>Cette campagne teste les questions préparées. Le résultat final apparaîtra lorsqu’elle sera terminée.</p></div><button className="catalog-link" onClick={() => open(runningCampaign.id)}>Voir l’avancement</button></section>}
    <section className="campaign-launch"><div><span className="step-number">CAMPAGNE EXPLORATOIRE</span><h2>Générer puis attaquer le Chat</h2><p>Groq formule 12 nouvelles questions à partir de nos intentions de risque. Le système les exécute contre la vraie API, vérifie les règles de sûreté et conserve chaque anomalie trouvée.</p><small>Cette campagne nécessite une clé Groq configurée dans le service Testing.</small></div><div className="launch-actions"><button className="primary launch" disabled={starting} onClick={() => startCampaign("exploration")}>{starting ? "Génération…" : "Lancer l’exploration IA"} <b>↗</b></button></div></section>
    <section className={`web-campaign ${!visualRunning && visibleCoverage?.available && visibleSummary.failed === 0 ? "pass" : ""}`}><div><span>CONTRÔLE VISUEL DU CHAT · PLAYWRIGHT</span><h2>{visualRunning ? `Contrôle visuel en cours — ${visualProgress.completed ?? 0} / ${visualProgress.total ?? "?"}` : visibleCoverage?.available ? `${visibleSummary.passed} / ${visibleSummary.total} parcours de l’interface Chat réussis` : "Aucun contrôle visuel disponible"}</h2><p>{visualRunning ? "Le navigateur automatisé vérifie réellement le Chat. Le journal et les compteurs se mettent à jour ici." : visibleCoverage?.available ? `Dernière exécution : ${formatDate(visibleCoverage.generated_at)}. Ce test reste séparé d’une campagne Groq.` : "Lancez le premier contrôle visuel depuis cette page."}</p>{visualRunning && <><div className="visual-progress"><i style={{ width: `${visualProgress.total ? Math.round((visualProgress.completed ?? 0) / visualProgress.total * 100) : 8}%` }} /></div><details className="visual-log" open><summary>Journal en direct</summary><pre>{visualLogs.map((event) => event.line).join("\n") || "Démarrage de Playwright…"}</pre></details></>}</div><div className="web-campaign-mark"><b>{visualRunning ? "EN COURS" : visualCheck?.status === "failed" || visualCheck?.status === "technical_error" ? "ÉCHEC" : visibleCoverage?.available && visibleSummary.failed === 0 ? "PASS" : "EN ATTENTE"}</b><small>Test d’interface</small><button className="primary visual-launch" disabled={visualRunning} onClick={startVisualCheck}>{visualRunning ? "Exécution…" : "Lancer le contrôle"}</button></div></section>
  </div>;
}

function Metric({ label, value, kind = "" }) { const details = { "Intentions de risque": "contrats de sûreté locaux", "Derniers scénarios IA": "générés, pas écrits à la main", "Failles détectées": "échecs ou alertes", "Cas à investiguer": "preuve insuffisante" }; return <article className={`metric ${kind}`}><span>{label}</span><strong>{value}</strong><small>{details[label] ?? "—"}</small></article>; }

function CampaignList({ campaigns, open }) {
  if (!campaigns.length) return <div className="empty-state">Aucune campagne n’a encore été lancée. L’exploration IA est prête dès que Groq est configuré.</div>;
  const labelFor = (campaign) => campaign.configuration?.scenario_profile === "exploration" ? "Exploration IA des failles" : campaign.configuration?.scenario_profile === "behavior" ? "Comportements conversationnels" : campaign.configuration?.trigger === "diagnostic" ? "Diagnostic technique" : "Catalogue de référence";
  return <div className="scenario-table"><div className="table-head"><span>CAMPAGNE</span><span>SCÉNARIOS</span><span>API + WEB</span><span>STATUT</span><span>LANCÉE LE</span></div>{campaigns.map((campaign) => <button className="scenario-row" key={campaign.id} onClick={() => open(campaign.id)}><div><b>{campaign.id}</b><small>{labelFor(campaign)}</small></div><span>{campaign.result?.summary?.total ?? "—"}</span><span>{campaign.configuration?.include_web ? "Oui" : "API"}</span><Status value={campaign.status} /><time>{formatDate(campaign.created_at)}</time></button>)}</div>;
}

function CampaignHistory({ campaigns, open }) {
  return <div className="page"><section className="intro"><p className="eyebrow">HISTORIQUE DES CAMPAGNES</p><h1>Revoir.<br /><em>Comprendre.</em></h1><p>Choisissez une campagne pour consulter ses scénarios, décisions et rapports.</p></section><CampaignList campaigns={campaigns} open={open} /></div>;
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
    ["generator", "Generator IA", "Crée de nouvelles questions à partir des intentions de risque."],
    ["planner", "Planner IA", "N’autorise qu’un message sûr vers l’API locale du Chat."],
    ["executor", "Executor · passage initial", "Interroge le Chat avec les seules questions retenues par le Planner."],
    ["evaluator", "Evaluator · passage initial", "Compare les réponses aux contrats de sûreté et aux preuves disponibles."],
    ["critic", "Critic IA", "Décide si une contre-vérification est réellement nécessaire."],
  ];
  const confirmationStages = [
    ["planner_confirmation", "Planner IA · contre-vérification", "Autorise les questions complémentaires demandées par le Critic."],
    ["executor_confirmation", "Executor · contre-vérification", "Interroge le Chat uniquement sur les points à confirmer."],
    ["evaluator_confirmation", "Evaluator · contre-vérification", "Évalue les réponses complémentaires."],
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
  return <div className="page detail-page"><button className="back" onClick={onBack}>← Retour aux campagnes</button><div className="detail-head"><div><p className="eyebrow">{campaign?.id ?? "Campagne"}</p><h1>La boucle de validation</h1><p>{campaign?.configuration?.include_web ? "API et interface Web sont prévues dans cette campagne." : "Cette campagne est limitée à l’API."}</p></div><Status value={campaign?.status} /></div>
    <section className="flow interactive-flow"><div className="flow-title"><span>ÉTAPES EXÉCUTABLES ET CONSULTABLES</span><small>La contre-vérification apparaît seulement si le Critic la demande.</small></div>{activeStages.map(([key, name, description], index) => { const event = stageEvent(key); const hasLiveResult = (key === "evaluator" || key === "evaluator_confirmation") && scenariosForStage(key).length > 0; const status = event?.status ?? (hasLiveResult ? "running" : campaign?.status === "pending" ? "pending" : "waiting"); const progress = event?.completed !== undefined && event?.total ? ` · ${event.completed} / ${event.total}` : ""; return <button type="button" className={`flow-step ${event || hasLiveResult ? "done" : ""} ${resolvedSelectedStage === key ? "active" : ""}`} onClick={() => selectStage(key)} key={key}><b>{String(index + 1).padStart(2, "0")}</b><strong>{name}</strong><small>{description}{progress}</small><Status value={status} /></button>; })}</section>
    <section className="stage-panel"><div className="stage-panel-heading"><div><span>AGENT · {selected[1].toUpperCase()}</span><h2>Rôle : {selected[2]}</h2></div><Status value={data?.status ?? (terminal ? "skipped" : "pending")} /></div><StageEvidence stage={resolvedSelectedStage} data={data} scenarios={stageScenarios} campaign={campaign} /></section>
  </div>;
}

function ObservedResponse({ execution }) {
  const api = execution?.api;
  const web = execution?.web;
  const response = api?.response;
  if (response?.type === "numeric") return <div className="observed-result">
    <span className="observed-label">RÉPONSE OBTENUE</span>
    <strong className="observed-value">{formatValue(response.value)}</strong>
    <span className="observed-unit">{metricLabels[response.metric_id] ?? response.metric_id} · {formatScale(response.unit_scale, response.currency)} · exercice {response.reporting_year}</span>
    <dl className="observed-metadata">
      <div><dt>Source</dt><dd>{response.source_document?.split("/").pop() ?? "—"}</dd></div>
      <div><dt>Page</dt><dd>{response.page_number ?? "—"}</dd></div>
    </dl>
    {response.source_excerpt && <blockquote>{response.source_excerpt}</blockquote>}
  </div>;
  if (response?.type === "document") return <div className="observed-result">
    <span className="observed-label">RÉPONSE DOCUMENTAIRE OBTENUE</span>
    <p>{response.analysis?.direct_answer ?? response.answer ?? response.message ?? "Réponse documentaire reçue."}</p>
    {response.evidence?.length > 0 && <ul>{response.evidence.slice(0, 3).map((item, index) => <li key={index}>{item.source_document?.split("/").pop() ?? "Rapport officiel"}{item.page_number ? ` · p. ${item.page_number}` : ""}</li>)}</ul>}
  </div>;
  if (response) return <div className="observed-result">
    <span className="observed-label">RÉPONSE OBTENUE</span>
    <p>{response.message ?? response.answer ?? "Réponse reçue."}</p>
  </div>;
  if (web) return <div className="observed-result"><span className="observed-label">RÉPONSE VISIBLE DANS LE WEB</span><p>{web.visible_text ?? "Réponse Web reçue."}</p></div>;
  return <p>La réponse n’a pas été conservée pour cette ancienne campagne.</p>;
}

function ValidationExplanation({ scenario }) {
  if (scenario.category === "cross_channel") return <p className="validation-explanation"><b>Validation :</b> la même question est posée à l’API et à l’interface Web ; type, valeur, année et source doivent être identiques.</p>;
  if (scenario.category === "conversation" || scenario.scenario_id?.startsWith("BEHAVIOR")) return <p className="validation-explanation"><b>Validation :</b> le contrat de comportement est vérifié : bonne catégorie de réponse, aucune valeur inventée et message ou preuve attendus.</p>;
  if (scenario.scenario_id?.startsWith("MISSING")) return <p className="validation-explanation"><b>Validation :</b> aucune donnée chiffrée ne doit être inventée lorsqu’aucun fait auto-validé n’existe.</p>;
  return <p className="validation-explanation"><b>Validation :</b> comparaison stricte avec le fait auto-validé : banque, métrique, exercice, valeur, unité, document, page et extrait PDF.</p>;
}

function EvaluatorDetails({ scenario }) {
  const detail = scenario.evaluator;
  const failedChecks = detail?.deterministic_checks?.filter((check) => check.passed === false) ?? [];
  const provider = detail?.provider;
  return <><ValidationExplanation scenario={scenario} /><p><b>Scores de contrôle :</b> pertinence {scenario.scores?.relevance}/5 · exactitude {scenario.scores?.factuality}/5 · source {scenario.scores?.source_fidelity}/5 · cohérence {scenario.scores?.coherence}/5</p>{detail?.rationale && <p><b>Conclusion de l’Evaluator :</b> {detail.rationale}</p>}{provider?.status === "failed" && <p><b>Évaluation Groq indisponible :</b> {provider.error ?? "erreur non détaillée"}</p>}{detail?.probable_cause && <p><b>Cause probable :</b> {detail.probable_cause}</p>}{failedChecks.length > 0 && <p><b>Règles en échec :</b> {failedChecks.map((check) => check.name).join(" · ")}</p>}</>;
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
    if (outputs.length) return <>{data?.reason && <p className="stage-copy"><b>Cause de l’arrêt :</b> {data.reason}</p>}<p className="stage-copy">{stage === "generator" ? providerErrors ? `${outputs.length} tentative(s) Groq pour ${targetCount ?? "—"} objectif(s) : ${accepted} question(s) générée(s), puis campagne interrompue par Groq. Ce n’est pas un rejet par les garde-fous.` : invalidOutputs ? `${outputs.length} tentative(s) pour ${targetCount ?? "—"} objectif(s) : ${invalidOutputs} réponse(s) IA invalide(s), rejetée(s) par le validateur local avant toute exécution.` : targetReached ? `${outputs.length} tentative(s), dont ${replacementAttempts} remplacement(s), pour atteindre l’objectif de ${targetCount} scénarios sûrs : ${accepted} question(s) nouvelles et ${rejected} écartée(s) par les garde-fous.` : `${outputs.length} tentative(s), dont ${replacementAttempts} remplacement(s), pour l’objectif de ${targetCount ?? "—"} scénarios : ${accepted} question(s) nouvelles et ${rejected} écartée(s) par les garde-fous. L’objectif n’a pas encore été atteint.` : `${outputs.length} action(s) examinée(s) : ${accepted} autorisée(s), ${rejected} rejetée(s). Le Planner ne peut autoriser qu’un message vers l’API locale du Chat.`}</p><div className="evaluation-list">{outputs.map((output) => <article key={output.id}><div><b>{output.question ?? output.charter ?? output.scenario_id}</b><small>{output.scenario_id ?? output.charter ?? "—"} · modèle {output.provider?.model ?? "—"}</small></div><Status value={outputStatus(output)} /><span>{output.provider?.status === "success" ? "JSON conforme" : output.provider?.error ?? "—"}</span></article>)}</div></>;
  }
  if (stage === "critic") {
    const reviewed = scenarios.filter((scenario) => scenario.critic);
    if (reviewed.length) return <><p className="stage-copy">Le Critic relit les anomalies. Il peut demander une question de confirmation et créer un test de régression lorsqu’une faille est confirmée.</p><div className="evaluation-list">{reviewed.map((scenario) => <article key={scenario.id}><div><b>{scenario.question ?? scenario.title}</b><small>{scenario.scenario_id} · confiance {Math.round((scenario.critic?.confidence ?? 0) * 100)} %</small><details className="observed-answer"><summary>Voir la décision du Critic</summary><p><b>Décision :</b> {scenario.critic?.reason ?? "—"}</p>{scenario.critic?.provider?.status === "failed" && <p><b>Critic Groq indisponible :</b> {scenario.critic.provider.error ?? "erreur non détaillée"}</p>}{scenario.critic?.follow_up_question && <p><b>Question de confirmation :</b> {scenario.critic.follow_up_question}</p>}{scenario.regression && <p><b>Régression :</b> {scenario.regression.created ? "créée" : "déjà connue"} · {scenario.regression.regression_id}</p>}</details></div><Status value={scenario.verdict} /><span>{scenario.critic?.create_regression_test ? "régression candidate" : scenario.critic?.next_action_required ? "confirmation demandée" : "aucune action"}</span></article>)}</div></>;
  }
  if (["evaluator", "executor", "evaluator_confirmation", "executor_confirmation"].includes(stage)) { const isExecutor = stage.startsWith("executor"); return <><p className="stage-copy">{scenarios.length ? (isExecutor ? `${scenarios.length} réponse(s) du Chat reçue(s) immédiatement. L’évaluation de qualité continue séparément.` : `${scenarios.length} verdict(s) métier reçus. Ouvrez une ligne pour voir les règles, la cause et la conclusion.`) : "Les résultats apparaîtront ici pendant l’exécution."}</p>{scenarios.length > 0 && <div className="evaluation-list">{scenarios.map((scenario) => <article key={scenario.id}><div><b>{scenario.index} / {scenario.total} · {scenario.question ?? scenario.title}</b><small>{scenario.scenario_id} · {isExecutor ? `API HTTP ${scenario.execution?.api?.http_status ?? "—"} · ${scenario.execution?.api?.latency_ms ?? "—"} ms${scenario.execution?.web ? ` · Web ${scenario.execution.web.latency_ms} ms` : ""}` : scenario.channels?.join(" + ")}</small><details className="observed-answer"><summary>{isExecutor ? "Voir la réponse observée et sa preuve" : "Voir le détail de la validation"}</summary><p><b>Question :</b> {scenario.question ?? scenario.title}</p>{isExecutor ? <ObservedResponse execution={scenario.execution} /> : <EvaluatorDetails scenario={scenario} />}</details></div><Status value={isExecutor ? (scenario.execution?.api?.errors?.length ? "failed" : "completed") : scenario.verdict} /><span>{isExecutor ? scenario.execution?.api?.response_type ?? scenario.execution?.web?.response_type ?? "réponse non disponible" : scenario.failure_category ?? "contrôles réussis"}</span></article>)}</div>}</>; }
  if (stage === "reporter" && campaign?.result?.report_paths) {
    const summary = campaign.result.summary ?? {};
    const labels = {
      summary_html: "Ouvrir la synthèse",
      audit_html: "Ouvrir l’audit détaillé",
    };
    const availableFormats = Object.keys(labels).filter((format) => campaign.result.report_paths[format] || campaign.result.report_paths.json);
    return <><p className="stage-copy">Choisissez la synthèse pour une vue rapide ou l’audit pour examiner chaque scénario.</p><section className="report-summary"><div><span>SCÉNARIOS</span><strong>{summary.total ?? "—"}</strong></div><div><span>VALIDÉS</span><strong>{summary.pass ?? 0}</strong></div><div><span>FAILLES</span><strong>{summary.fail ?? 0}</strong></div><div><span>À CONFIRMER</span><strong>{summary.inconclusive ?? 0}</strong></div></section><div className="report-actions">{availableFormats.map((format) => <a key={format} href={`${API}/api/campaigns/${campaign.id}/reports/${format}`} target="_blank" rel="noreferrer" className="primary">{labels[format]} <b>↗</b></a>)}</div></>;
  }
  if (!data) return <p className="stage-copy">Cette étape n’a pas encore produit de donnée.</p>;
  return <dl className="evidence-list">{Object.entries(data).filter(([key]) => !["id", "created_at", "type", "stage"].includes(key)).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "—")}</dd></div>)}</dl>;
}

createRoot(document.getElementById("root")).render(<App />);
