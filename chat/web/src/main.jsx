import React, { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./brand.css";
import "./universe.css";
import "./document.css";
import "./workspace.css";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const examples = ["Quel est le PNB de BIAT en 2025 ?", "Quels sont les dépôts à vue de BIAT en 2025 ?", "Quel est le résultat net de BIAT en 2024 ?"];
const banks = [["BIAT", "35 FAITS VALIDÉS"], ["Amen Bank", "35 FAITS VALIDÉS"], ["Attijari Bank", "35 FAITS VALIDÉS"], ["Banque de Tunisie", "35 FAITS VALIDÉS"], ["Banque Zitouna", "34 FAITS VALIDÉS"]];
const number = (value) => new Intl.NumberFormat("fr-FR").format(Number(value));
const noteTitle = (text) => text.match(/(?:NOTE|Note)\s+[IVXLCDM0-9]+\s*[–-]\s*[^\n]+/)?.[0]
  ?? text.split("\n").map((line) => line.trim()).find((line) => line.length > 2)?.slice(0, 90)
  ?? "Passage du rapport officiel";
const sourcePreview = (text) => {
  const heading = text.search(/(?:NOTE|Note)\s+[IVXLCDM0-9]+\s*[–-]/);
  const start = heading >= 0 ? heading : 0;
  const excerpt = text.slice(start, start + 420).trim();
  return start + 420 < text.length ? `${excerpt}…` : excerpt;
};
const metricLabels = {
  net_banking_income: "PNB",
  net_income: "résultat net",
  demand_deposits: "dépôts à vue",
  total_assets: "total des actifs",
  customer_loans_gross: "crédits bruts",
};

function DocumentAnswer({ data, openDocument }) {
  const primary = data.evidence[0];
  const analysis = data.analysis;
  const isExpansion = analysis?.intent === "scope_expansion";
  const answer = analysis?.direct_answer ?? data.answer;

  return <><small>MYFINANCE</small><div className="document-result">
    <section className="document-answer">
      <p>{answer}</p>
      {isExpansion && analysis.findings.map((item) => <p className="document-detail" key={item.title}><b>{item.title}.</b> {item.text}{item.pages?.length > 0 && ` [${item.pages.map((page) => `p. ${page}`).join(", ")}]`}</p>)}
      {isExpansion && <p className="document-caveat">{analysis.scope_explanation}</p>}
      <small className="document-reference">Source : {noteTitle(primary?.text ?? "")} · p. {primary?.page_number}</small>
    </section>
    <details className="source-details"><summary>Voir les passages du rapport ({data.evidence.length})</summary>{data.evidence.map((item) => <article key={item.chunk_id}><div><small>Rapport officiel · page {item.page_number}</small><button onClick={() => openDocument(item.source_path)}>Ouvrir le PDF ↗</button></div><blockquote>{sourcePreview(item.text)}</blockquote></article>)}</details>
  </div></>;
}

function courtesyResponse(message) {
  const text = message.trim().toLowerCase();
  if (/^(?:bonjour|bonsoir|salut|coucou)[!. ]*$/i.test(text)) {
    return "Bonjour. Je suis prêt à analyser les rapports financiers disponibles. Indiquez simplement une banque, une année et ce que vous souhaitez comprendre — par exemple : « Quel est le PNB de BIAT en 2025 ? »";
  }
  if (/^(?:merci|merci beaucoup|thanks)[!. ]*$/i.test(text)) {
    return "Avec plaisir. Je reste à votre disposition pour poursuivre l’analyse ou vérifier un autre indicateur.";
  }
  return "";
}

function App() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [dossier, setDossier] = useState({ mode: "idle", bank_id: null, bank_name: null, reporting_year: null, topic: null, metric_id: null });
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState("analysis");

  async function analyse(nextQuestion = question) {
    if (!nextQuestion.trim()) return;
    const courtesy = courtesyResponse(nextQuestion);
    if (courtesy) {
      setQuestion("");
      setMessages((current) => [...current, { role: "user", text: nextQuestion }, { role: "assistant", type: "courtesy", text: courtesy }]);
      return;
    }
    setQuestion("");
    setLoading(true);
    try {
      const response = await fetch(API + "/api/conversation/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: nextQuestion, context: dossier }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error("conversation unavailable");
      const corrections = body.normalization?.corrections ?? [];
      const correctionNote = corrections.length ? `Orthographe : ${corrections.map((item) => `${item.from} → ${item.to}`).join(", ")}` : "";
      const completedDocumentDossier = body.type === "document" && dossier.mode === "document"
        && (!dossier.bank_id || !dossier.reporting_year);
      const continuedDocumentDossier = body.type === "document" && dossier.mode === "document"
        && !completedDocumentDossier;
      const applied = completedDocumentDossier
        ? `Dossier complété · ${body.context.bank_name} · ${body.context.reporting_year}`
        : continuedDocumentDossier
          ? `Analyse poursuivie · ${body.context.bank_name} · ${body.context.reporting_year}`
          : correctionNote;
      setMessages((current) => [...current, { role: "user", text: nextQuestion, applied }]);
      setDossier(body.context ?? dossier);
      if (body.type === "clarification") {
        setMessages((current) => [...current, { role: "assistant", type: "clarification", text: body.message }]);
        return;
      }
      if (body.type === "document") {
        setMessages((current) => [...current, { role: "assistant", type: "document", data: body }]);
        return;
      }
      setMessages((current) => [...current, { role: "assistant", type: "numeric", data: body }]);
    } catch {
      setMessages((current) => [...current, { role: "assistant", type: "clarification", text: "Le moteur de réponse est inaccessible. Démarre l’API MyFinance puis réessaie." }]);
    }
    finally { setLoading(false); }
  }
  function openDocument(sourcePath) {
    const relative = sourcePath.replace("data/raw/official-reports/etat financier/", "").split("/").map(encodeURIComponent).join("/");
    const documentWindow = window.open(API + "/documents/" + relative, "_blank");
    if (documentWindow) documentWindow.opener = null;
  }
  const contextSummary = dossier.mode === "document"
    ? [dossier.bank_name, "Analyse documentaire", dossier.reporting_year].filter(Boolean).join(" · ")
    : [dossier.bank_name, dossier.metric_id && (metricLabels[dossier.metric_id] ?? dossier.metric_id.replaceAll("_", " ")), dossier.reporting_year].filter(Boolean).join(" · ");
  const pendingSummary = dossier.mode === "document" && (!dossier.bank_id || !dossier.reporting_year)
    ? `Précision attendue · ${[dossier.bank_name, dossier.topic].filter(Boolean).join(" · ") || "analyse documentaire"}`
    : "";

  return <main className="shell">
    <aside className="rail">
      <div className="brand">
        <span className="brand-seal" aria-hidden="true"><svg viewBox="0 0 42 42" fill="none"><path d="M7 31V11l8.2 12.1L21 14.6l5.8 8.5L35 11v20"/><path d="M7 35h28" className="seal-line"/><circle cx="34.5" cy="7.5" r="3.5" className="seal-dot"/></svg></span>
        <span className="brand-copy"><strong>MYFINANCE</strong><small>INTELLIGENCE / 6.5</small></span>
      </div>
      <nav><button className={view === "analysis" ? "active" : ""} onClick={() => setView("analysis")}>◈ Analyse</button><button className={view === "sources" ? "active" : ""} onClick={() => setView("sources")}>⌘ Sources</button><button className={view === "universe" ? "active" : ""} onClick={() => setView("universe")}>◌ Portefeuilles</button></nav>
      <div className="verified-rail"><i /> DONNÉES VALIDÉES AUTOMATIQUEMENT<small>BIAT · 2021 — 2025</small></div>
    </aside>
    <section className="work">
      <header><span>MYFINANCE 6.5 <i /> Banque individuelle</span><span><b /> RAPPORTS OFFICIELS <strong>25</strong></span></header>
      <div className={"content view-" + view} id="analysis">
        <p className="eyebrow">FINANCIAL INTELLIGENCE / TUNISIA</p>
        <h1>Des réponses nettes.<br/><em>Des preuves immédiates.</em></h1>
        <p className="lead">Interroge les états financiers avec la rigueur d’un analyste. Le fil conserve uniquement le contexte confirmé — banque, année, indicateur — et chaque réponse reste reliée à son rapport officiel.</p>
        <section className="panel conversation">
          <div className="panel-title"><span>01</span><div><b>Conversation d’analyse</b><small>{pendingSummary ? `Précision attendue · ${pendingSummary}` : contextSummary ? `Contexte retenu · ${contextSummary}` : "Aucun contexte retenu pour le moment"}</small></div><mark>● SOURCE-LOCKED</mark></div>
          {(messages.length > 0 || loading) && <div className="thread" aria-live="polite">
            {messages.map((message, index) => <div className={`message ${message.role} ${message.type ?? ""}`} key={index}>
               {message.role === "user" ? <><small>VOUS</small><p>{message.text}</p>{message.applied && <em>Contexte appliqué : {message.applied}</em>}</> : message.type === "numeric" ? <><small>MYFINANCE · VALEUR VALIDÉE AUTOMATIQUEMENT</small><div className="result"><div className="value"><small>{metricLabels[message.data.metric_id] ?? message.data.metric_id.replaceAll("_", " ")}</small><strong>{number(message.data.value)}</strong><p>{message.data.unit_scale === "thousand" ? "milliers de TND" : message.data.currency} · exercice {message.data.reporting_year}</p></div><article><div><small>PREUVE PRIMAIRE</small><b>PAGE {message.data.page_number}</b></div><blockquote>“{message.data.source_excerpt}”</blockquote><footer><em>PDF</em>{message.data.source_document.split("/").pop()} <button onClick={() => openDocument(message.data.source_document)}>Voir la source ↗</button></footer></article></div></> : message.type === "document" ? <DocumentAnswer data={message.data} openDocument={openDocument} /> : <><small>MYFINANCE</small><p>{message.text}</p></>}
            </div>)}
            {loading && <div className="message assistant pending"><small>MYFINANCE</small><p>Je vérifie le rapport officiel…</p></div>}
          </div>}
          <div className="composer"><textarea aria-label="Votre question" placeholder="Écrivez votre question ou une relance…" value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); analyse(); } }} /><button onClick={() => analyse()} disabled={loading}>{loading ? "ANALYSE…" : "ENVOYER"} <b>↗</b></button></div>
          <div className="suggest"><span>ESSAYER</span>{examples.map((item) => <button key={item} onClick={() => analyse(item)}>{item}</button>)}</div>
        </section>
        <section className="universe" id="universe"><div><span>UNIVERS BANCAIRE</span><h2>Les banques dans le radar.</h2><p>Les cinq banques et leurs rapports 2021–2025 sont présents. Les 174 faits affichés ont tous été validés automatiquement ; Zitouna 2021 conserve une absence volontaire de résultat net.</p></div><div className="bank-grid">{banks.map(([name, state]) => <article className="ready" key={name}><b>{name}</b><mark>{state}</mark><small>05 rapports · 2021 — 2025</small></article>)}</div></section>
        <section className="sources" id="sources"><div><span>REGISTRE DES SOURCES</span><h2>Chaque réponse peut être auditée.</h2><p>Chaque valeur conserve son rapport officiel, sa page et son extrait source.</p></div><dl><div><dt>25</dt><dd>rapports officiels</dd></div><div><dt>5</dt><dd>banques dans le corpus</dd></div><div><dt>2021—25</dt><dd>période disponible</dd></div></dl></section>
      </div>
    </section>
  </main>;
}
createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);
