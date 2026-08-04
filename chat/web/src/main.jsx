import React, { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./brand.css";
import "./universe.css";
import "./document.css";
import "./workspace.css";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const examples = ["What was BIAT's net banking income in 2025?", "What were BIAT's demand deposits in 2025?", "What was BIAT's net income in 2024?"];
const banks = [["BIAT", "35 VALIDATED FACTS"], ["Amen Bank", "35 VALIDATED FACTS"], ["Attijari Bank", "35 VALIDATED FACTS"], ["Banque de Tunisie", "35 VALIDATED FACTS"], ["Banque Zitouna", "34 VALIDATED FACTS"]];
const number = (value) => new Intl.NumberFormat("en-US").format(Number(value));
const noteTitle = (text) => text.match(/(?:NOTE|Note)\s+[IVXLCDM0-9]+\s*[–-]\s*[^\n]+/)?.[0]
  ?? text.split("\n").map((line) => line.trim()).find((line) => line.length > 2)?.slice(0, 90)
  ?? "Official report excerpt";
const sourcePreview = (text) => {
  const heading = text.search(/(?:NOTE|Note)\s+[IVXLCDM0-9]+\s*[–-]/);
  const start = heading >= 0 ? heading : 0;
  const excerpt = text.slice(start, start + 420).trim();
  return start + 420 < text.length ? `${excerpt}…` : excerpt;
};
const metricLabels = {
  net_banking_income: "PNB",
  net_income: "net income",
  demand_deposits: "demand deposits",
  total_assets: "total assets",
  customer_loans_gross: "gross loans",
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
      <small className="document-reference">Source: {noteTitle(primary?.text ?? "")} · p. {primary?.page_number}</small>
    </section>
    <details className="source-details"><summary>View report excerpts ({data.evidence.length})</summary>{data.evidence.map((item) => <article key={item.chunk_id}><div><small>Official report · page {item.page_number}</small><button onClick={() => openDocument(item.source_path)}>Open PDF ↗</button></div><blockquote>{sourcePreview(item.text)}</blockquote></article>)}</details>
  </div></>;
}

function courtesyResponse(message) {
  const text = message.trim().toLowerCase();
  if (/^(?:bonjour|bonsoir|salut|coucou|hello|hi)[!. ]*$/i.test(text)) {
    return "Hello. I am ready to analyse the available financial reports. Simply provide a bank, a year and what you want to understand — for example: “What was BIAT's net banking income in 2025?”";
  }
  if (/^(?:merci|merci beaucoup|thanks)[!. ]*$/i.test(text)) {
    return "You are welcome. I am available to continue the analysis or check another metric.";
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
      const correctionNote = corrections.length ? `Spelling: ${corrections.map((item) => `${item.from} → ${item.to}`).join(", ")}` : "";
      const completedDocumentDossier = body.type === "document" && dossier.mode === "document"
        && (!dossier.bank_id || !dossier.reporting_year);
      const continuedDocumentDossier = body.type === "document" && dossier.mode === "document"
        && !completedDocumentDossier;
      const applied = completedDocumentDossier
        ? `Context completed · ${body.context.bank_name} · ${body.context.reporting_year}`
        : continuedDocumentDossier
          ? `Analysis continued · ${body.context.bank_name} · ${body.context.reporting_year}`
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
      setMessages((current) => [...current, { role: "assistant", type: "clarification", text: "The answer engine is unavailable. Start the MyFinance API and try again." }]);
    }
    finally { setLoading(false); }
  }
  function openDocument(sourcePath) {
    const relative = sourcePath.replace("data/raw/official-reports/etat financier/", "").split("/").map(encodeURIComponent).join("/");
    const documentWindow = window.open(API + "/documents/" + relative, "_blank");
    if (documentWindow) documentWindow.opener = null;
  }
  const contextSummary = dossier.mode === "document"
    ? [dossier.bank_name, "Documentary analysis", dossier.reporting_year].filter(Boolean).join(" · ")
    : [dossier.bank_name, dossier.metric_id && (metricLabels[dossier.metric_id] ?? dossier.metric_id.replaceAll("_", " ")), dossier.reporting_year].filter(Boolean).join(" · ");
  const pendingSummary = dossier.mode === "document" && (!dossier.bank_id || !dossier.reporting_year)
    ? `Clarification needed · ${[dossier.bank_name, dossier.topic].filter(Boolean).join(" · ") || "documentary analysis"}`
    : "";

  return <main className="shell">
    <aside className="rail">
      <div className="brand">
        <span className="brand-seal" aria-hidden="true"><svg viewBox="0 0 42 42" fill="none"><path d="M7 31V11l8.2 12.1L21 14.6l5.8 8.5L35 11v20"/><path d="M7 35h28" className="seal-line"/><circle cx="34.5" cy="7.5" r="3.5" className="seal-dot"/></svg></span>
        <span className="brand-copy"><strong>MYFINANCE</strong><small>INTELLIGENCE / 6.5</small></span>
      </div>
      <nav><button className={view === "analysis" ? "active" : ""} onClick={() => setView("analysis")}>◈ Analysis</button><button className={view === "sources" ? "active" : ""} onClick={() => setView("sources")}>⌘ Sources</button><button className={view === "universe" ? "active" : ""} onClick={() => setView("universe")}>◌ Portfolios</button></nav>
      <div className="verified-rail"><i /> AUTOMATICALLY VALIDATED DATA<small>BIAT · 2021 — 2025</small></div>
    </aside>
    <section className="work">
      <header><span>MYFINANCE 6.5 <i /> Retail banking</span><span><b /> OFFICIAL REPORTS <strong>25</strong></span></header>
      <div className={"content view-" + view} id="analysis">
        <p className="eyebrow">FINANCIAL INTELLIGENCE / TUNISIA</p>
        <h1>Clear answers.<br/><em>Immediate evidence.</em></h1>
        <p className="lead">Explore financial statements with an analyst’s discipline. The conversation retains only confirmed context — bank, year and metric — and every answer remains linked to its official report.</p>
        <section className="panel conversation">
          <div className="panel-title"><span>01</span><div><b>Analysis conversation</b><small>{pendingSummary ? `Clarification needed · ${pendingSummary}` : contextSummary ? `Current context · ${contextSummary}` : "No context retained yet"}</small></div><mark>● SOURCE-LOCKED</mark></div>
          {(messages.length > 0 || loading) && <div className="thread" aria-live="polite">
            {messages.map((message, index) => <div className={`message ${message.role} ${message.type ?? ""}`} key={index}>
               {message.role === "user" ? <><small>YOU</small><p>{message.text}</p>{message.applied && <em>Applied context: {message.applied}</em>}</> : message.type === "numeric" ? <><small>MYFINANCE · AUTOMATICALLY VALIDATED VALUE</small><div className="result"><div className="value"><small>{metricLabels[message.data.metric_id] ?? message.data.metric_id.replaceAll("_", " ")}</small><strong>{number(message.data.value)}</strong><p>{message.data.unit_scale === "thousand" ? "thousand TND" : message.data.currency} · financial year {message.data.reporting_year}</p></div><article><div><small>PRIMARY EVIDENCE</small><b>PAGE {message.data.page_number}</b></div><blockquote>“{message.data.source_excerpt}”</blockquote><footer><em>PDF</em>{message.data.source_document.split("/").pop()} <button onClick={() => openDocument(message.data.source_document)}>View source ↗</button></footer></article></div></> : message.type === "document" ? <DocumentAnswer data={message.data} openDocument={openDocument} /> : <><small>MYFINANCE</small><p>{message.text}</p></>}
            </div>)}
            {loading && <div className="message assistant pending"><small>MYFINANCE</small><p>Checking the official report…</p></div>}
          </div>}
          <div className="composer"><textarea aria-label="Your question" placeholder="Write your question or a follow-up…" value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); analyse(); } }} /><button onClick={() => analyse()} disabled={loading}>{loading ? "ANALYSING…" : "SEND"} <b>↗</b></button></div>
          <div className="suggest"><span>TRY</span>{examples.map((item) => <button key={item} onClick={() => analyse(item)}>{item}</button>)}</div>
        </section>
        <section className="universe" id="universe"><div><span>BANKING UNIVERSE</span><h2>Banks on the radar.</h2><p>All five banks and their 2021–2025 reports are available. Each of the 174 displayed facts has been automatically validated; Zitouna 2021 deliberately has no net-income value.</p></div><div className="bank-grid">{banks.map(([name, state]) => <article className="ready" key={name}><b>{name}</b><mark>{state}</mark><small>05 reports · 2021 — 2025</small></article>)}</div></section>
        <section className="sources" id="sources"><div><span>SOURCE REGISTER</span><h2>Every answer can be audited.</h2><p>Every value retains its official report, page and source excerpt.</p></div><dl><div><dt>25</dt><dd>official reports</dd></div><div><dt>5</dt><dd>banks in the corpus</dd></div><div><dt>2021—25</dt><dd>available period</dd></div></dl></section>
      </div>
    </section>
  </main>;
}
createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);
