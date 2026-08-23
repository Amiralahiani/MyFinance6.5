import React, { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./brand.css";
import "./universe.css";
import "./document.css";
import "./workspace.css";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const examples = ["What is BIAT's current share price?", "Compare BIAT, BT and Amen Bank.", "How many shares made up BIAT's share capital in 2025?"];
const banks = [["BIAT", "35 VALIDATED FACTS"], ["Amen Bank", "35 VALIDATED FACTS"], ["Attijari Bank", "35 VALIDATED FACTS"], ["Banque de Tunisie", "35 VALIDATED FACTS"], ["Banque Zitouna", "34 VALIDATED FACTS"]];
const number = (value) => new Intl.NumberFormat("en-US").format(Number(value));
const metricUnit = (item) => item.unit_scale === "thousand" ? "thousand TND" : item.currency;
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
  const answer = (analysis?.direct_answer ?? data.answer).replace(/\s*\[p\.\s*\d+\]/gi, "").trim();

  return <><small>MYFINANCE</small>
    <p>{answer}</p>
    {isExpansion && analysis.findings.map((item) => <p className="document-detail" key={item.title}><b>{item.title}.</b> {item.text}{item.pages?.length > 0 && ` [${item.pages.map((page) => `p. ${page}`).join(", ")}]`}</p>)}
    {isExpansion && <p className="document-caveat">{analysis.scope_explanation}</p>}
    <div className="message-source"><button onClick={() => openDocument(primary.source_path)}>Source · {primary?.bank_name} · {primary?.reporting_year} · p. {primary?.page_number} ↗</button></div>
    <details className="source-details"><summary>{data.evidence.length === 1 ? "View excerpt" : `View ${data.evidence.length} excerpts`}</summary>{data.evidence.map((item) => <article key={item.chunk_id}><div><small>{item.bank_name} financial report · p. {item.page_number}</small><button onClick={() => openDocument(item.source_path)}>Open PDF ↗</button></div><blockquote>{sourcePreview(item.text)}</blockquote></article>)}</details>
  </>;
}

function ComparisonAnswer({ data, openDocument }) {
  const label = metricLabels[data.metric_id] ?? data.metric_id.replaceAll("_", " ");
  return <><small>MYFINANCE</small><p>{label} · financial year {data.reporting_year}</p>
    <ComparisonChart data={data} label={label} />
    <ComparisonSources values={data.values} openDocument={openDocument} />
  </>;
}

function ComparisonAnalysisAnswer({ data, openDocument }) {
  const label = metricLabels[data.metric_id] ?? data.metric_id.replaceAll("_", " ");
  return <><small>MYFINANCE · COMPARATIVE REPORT ANALYSIS</small>
    <p className="comparison-reading">{data.answer}</p>
    <ComparisonChart data={data} label={label} />
    <ComparisonSources values={data.values} openDocument={openDocument} />
    <small className="general-note">{label} · financial year {data.reporting_year} · based only on official-report excerpts</small>
    <details className="source-details"><summary>{data.evidence.length === 1 ? "View supporting excerpt" : `View ${data.evidence.length} supporting excerpts`}</summary>{data.evidence.map((item) => <article key={item.chunk_id}><div><small>{item.bank_name} financial report · p. {item.page_number}</small><button onClick={() => openDocument(item.source_path)}>Open PDF ↗</button></div><blockquote>{sourcePreview(item.text)}</blockquote></article>)}</details>
  </>;
}

function MultiMetricComparisonAnalysisAnswer({ data, openDocument }) {
  return <><small>MYFINANCE · MULTI-METRIC COMPARATIVE ANALYSIS</small>
    <p className="comparison-reading">{data.answer}</p>
    <div className="metric-dashboard">{data.metrics.map((metric) => {
      const label = metricLabels[metric.metric_id] ?? metric.metric_id.replaceAll("_", " ");
      return <section key={metric.metric_id}>
        <header><span>{label}</span><small>financial year {metric.reporting_year}</small></header>
        <ComparisonChart data={metric} label={label} />
        <ComparisonSources values={metric.values} openDocument={openDocument} />
      </section>;
    })}</div>
    <small className="general-note">{data.analysis.scope_explanation}</small>
  </>;
}

function ComparisonChart({ data, label }) {
  const values = [...data.values].sort((left, right) => Number(right.value) - Number(left.value));
  if (values.length < 2) return null;
  const highest = Number(values[0].value);
  const lowest = Number(values.at(-1).value);
  const difference = highest - lowest;
  const multiple = lowest ? highest / lowest : null;
  return <figure className="comparison-chart" aria-label={`${label} comparison for ${data.reporting_year}`}>
    <figcaption><span>COMPARISON VIEW</span><strong>Reported-value ranking</strong><small>Each bar is scaled to the leading reported value.</small></figcaption>
    <ol>{values.map((item, index) => {
      const percentage = highest ? Math.max(3, (Number(item.value) / highest) * 100) : 0;
      return <li key={item.bank_id}>
        <b>{String(index + 1).padStart(2, "0")}</b>
        <span className="chart-bank">{item.bank_name}</span>
        <span className="chart-track" aria-hidden="true"><i style={{ width: `${percentage}%` }} /></span>
        <strong>{number(item.value)}</strong>
        <small>{metricUnit(item)}</small>
      </li>;
    })}</ol>
    <footer><span>Range</span><strong>{number(difference)} {metricUnit(values[0])}</strong>{multiple && <em>{multiple.toFixed(1)}× from highest to lowest</em>}</footer>
  </figure>;
}

function ComparisonSources({ values, openDocument }) {
  return <details className="comparison-sources">
    <summary>{values.length} primary report sources</summary>
    <div>{values.map((item) => <button key={item.bank_id} onClick={() => openDocument(item.source_path)}>{item.bank_name} <span>p. {item.page_number} ↗</span></button>)}</div>
  </details>;
}

function SourceValueAnswer({ data, openDocument }) {
  const unit = data.unit_scale === "thousand" ? "thousand TND" : data.currency;
  return <><small>MYFINANCE</small><p>{data.context.bank_name} reported {number(data.value)} {unit} for {data.source_label} in {data.reporting_year}.</p>
    <div className="message-source"><button onClick={() => openDocument(data.source_document)}>Source · official financial report · p. {data.page_number} ↗</button></div>
    <details className="source-details"><summary>View excerpt</summary><article><blockquote>{data.source_excerpt}</blockquote></article></details>
  </>;
}

function MetricAnalysisAnswer({ data }) {
  return <><small>MYFINANCE · REPORT CONTEXT</small><p>{data.answer}</p><small className="general-note">Based on the available reported values; not a market or valuation judgment</small></>;
}

function GeneralAnswer({ data }) {
  const sources = Array.isArray(data.sources) ? data.sources : [];
  const note = data.source_status === "official_source_required" ? "Official source required · no verified source configured" : "General guidance · not extracted from a bank report";
  return <><small>MYFINANCE · GENERAL EXPLANATION</small><p>{data.answer}</p>{sources.length > 0 ? <div className="general-sources">{sources.map((source) => <a key={source.source_id} href={source.url} target="_blank" rel="noreferrer">Official source · {source.title} ↗</a>)}</div> : <small className="general-note">{note}</small>}</>;
}

function MarketStatusAnswer({ data }) {
  const instruments = data.availability?.requested_instruments ?? [];
  const verified = data.availability?.verified_source_ids ?? [];
  return <section className="market-notice"><small>MYFINANCE · MARKET WATCH</small><h3>Market data status</h3><p>{data.answer}</p>
    {instruments.length > 0 && <div className="market-status-list">{instruments.map((instrument) => <span key={instrument.bank_id}>{instrument.bank_name} · {instrument.identity_status === "verified" ? `${instrument.exchange}${instrument.exchange_symbol ? ` · ${instrument.exchange_symbol}` : ""}` : "listing not available"}</span>)}</div>}
    <small className="general-note">{data.availability?.active ? "Official source active" : verified.length > 0 ? "Official collection verified" : "No approved market observation"}</small>
  </section>;
}

function CollectionHealth({ health }) {
  if (!health) return null;
  const label = health.status === "fresh" ? "Collection current" : health.status === "collection_failed" ? "Collection failed" : health.status === "stale" ? "Collection delayed" : "No snapshots yet";
  return <section className={`collection-health ${health.fresh ? "fresh" : "stale"}`} role={health.alerts?.length ? "alert" : undefined}>
    <div><small>MARKET COLLECTION</small><strong>{label}</strong></div>
    <div><p>{health.snapshot_count ?? 0} snapshot(s){health.age_minutes != null ? ` · last collection ${number(health.age_minutes)} min ago` : ""}</p>{health.alerts?.map((alert) => <p className="collection-alert" key={alert.code}>{alert.severity.toUpperCase()}: {alert.message}</p>)}</div>
  </section>;
}

function MarketQuoteAnswer({ data }) {
  const quote = data.quote;
  const direction = quote.change_percent > 0 ? "up" : quote.change_percent < 0 ? "down" : "unchanged";
  const captured = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(quote.retrieved_at));
  const movement = direction === "unchanged" ? "No change shown" : `${direction === "up" ? "Up" : "Down"} this session`;
  return <section className="market-quote-card">
    <header><div><small>MYFINANCE · MARKET WATCH</small><h3>{quote.bank_name}</h3></div><span>#{quote.mnemonic}</span></header>
    {data.answer && <p className="market-reading">{data.answer}</p>}
    <div className="market-price"><div><small>CURRENT SHARE PRICE</small><strong>{number(quote.price)}</strong><p>{quote.currency}</p></div><div className={`market-move ${direction}`}><small>SESSION CHANGE</small><b>{quote.change_percent > 0 ? "+" : ""}{quote.change_percent.toFixed(2)}%</b><p>{movement}</p></div></div>
    <footer><span>Captured {captured}{quote.delay_notice ? ` · delayed ${quote.delay_notice}` : ""}</span><span>ISIN {quote.isin}</span><a href={quote.source_url} target="_blank" rel="noreferrer">Open Market Watch ↗</a></footer>
  </section>;
}

function MarketComparisonAnswer({ data }) {
  const quotes = data.quotes ?? [];
  const captured = quotes[0]?.retrieved_at
    ? new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(quotes[0].retrieved_at))
    : null;
  return <section className="market-comparison-card">
    <header><div><small>MYFINANCE · MARKET WATCH</small><h3>Current share-price comparison</h3></div><span>{quotes.length} BANKS</span></header>
    {data.answer && <p className="market-reading">{data.answer}</p>}
    <div className="market-comparison-values">{quotes.map((quote) => {
      const direction = quote.change_percent > 0 ? "up" : quote.change_percent < 0 ? "down" : "unchanged";
      return <article key={quote.bank_id}><div><b>{quote.bank_name}</b><small>#{quote.mnemonic}</small></div><strong>{number(quote.price)}</strong><span>{quote.currency}</span><em className={direction}>{quote.change_percent > 0 ? "+" : ""}{quote.change_percent.toFixed(2)}%</em></article>;
    })}</div>
    <footer><span>Prices shown by the official Market Watch{captured ? ` · captured ${captured}` : ""}{quotes[0]?.delay_notice ? ` · delayed ${quotes[0].delay_notice}` : ""}</span>{quotes[0]?.source_url && <a href={quotes[0].source_url} target="_blank" rel="noreferrer">Open Market Watch ↗</a>}</footer>
  </section>;
}

function MarketOverviewAnswer({ data }) {
  const summary = data.summary;
  const captured = summary.retrieved_at
    ? new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(summary.retrieved_at))
    : null;
  const metrics = [
    ["Market capitalisation", number(summary.market_capitalization_tnd), "TND"],
    ["Turnover", number(summary.traded_value_tnd), "TND"],
    ["Transactions", number(summary.transactions), "trades"],
    ["Active values", `${number(summary.active_values)} / ${number(summary.listed_values)}`, "listed"],
  ];
  return <section className="market-overview-card">
    <header><div><small>MYFINANCE · MARKET WATCH</small><h3>Bourse de Tunis · session overview</h3></div><span>LIVE SESSION</span></header>
    <div className="market-breadth"><div><small>ADVANCING</small><strong>{number(summary.advances)}</strong></div><div><small>DECLINING</small><strong>{number(summary.declines)}</strong></div><div><small>SHARES TRADED</small><strong>{number(summary.traded_quantity)}</strong></div></div>
    <div className="market-overview-metrics">{metrics.map(([label, value, unit]) => <article key={label}><small>{label}</small><strong>{value}</strong><span>{unit}</span></article>)}</div>
    <footer><span>Official session snapshot{captured ? ` · captured ${captured}` : ""}{summary.delay_notice ? ` · delayed ${summary.delay_notice}` : ""}</span>{summary.source_url && <a href={summary.source_url} target="_blank" rel="noreferrer">Open Market Watch ↗</a>}</footer>
  </section>;
}

function MarketPerformanceAnswer({ data }) {
  const performance = data.performance;
  const direction = performance.performance_percent > 0 ? "up" : performance.performance_percent < 0 ? "down" : "unchanged";
  const points = performance.points ?? [];
  const closes = points.map((point) => point.close).filter(Number.isFinite);
  const minimum = Math.min(...closes), maximum = Math.max(...closes), range = maximum - minimum || 1;
  const path = closes.map((close, index) => `${index === 0 ? "M" : "L"}${(index / Math.max(closes.length - 1, 1)) * 100} ${100 - ((close - minimum) / range) * 100}`).join(" ");
  const captured = performance.retrieved_at ? new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(performance.retrieved_at)) : null;
  return <section className="market-performance-card">
    <header><div><small>MYFINANCE · MARKET HISTORY</small><h3>{performance.bank_name} · {performance.year}</h3></div><span>#{performance.mnemonic}</span></header>
    <div className="market-performance-summary"><div><small>PERFORMANCE</small><strong className={direction}>{performance.performance_percent > 0 ? "+" : ""}{performance.performance_percent.toFixed(2)}%</strong><p>{number(performance.first_close)} → {number(performance.last_close)} {performance.currency}</p></div><figure><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`${performance.bank_name} closing-price history`}><path d={path} /></svg><figcaption>{performance.first_date} <span>Closing prices · {points.length} sessions</span> {performance.last_date}</figcaption></figure></div>
    <footer><span>{performance.series_origin === "stored_snapshots" ? "Auditable local snapshots" : "Official historical series"}{captured ? ` · retrieved ${captured}` : ""}</span>{performance.source_url && <a href={performance.source_url} target="_blank" rel="noreferrer">Open official history ↗</a>}</footer>
  </section>;
}

function MarketActivityAnswer({ data }) {
  const activity = data.activity;
  const labels = {
    volume: ["Volume", "shares"], turnover_tnd: ["Turnover", "TND"],
    transactions: ["Transactions", "trades"], market_capitalization_md: ["Market capitalisation", "MD"],
  };
  return <section className="market-overview-card">
    <header><div><small>MYFINANCE · MARKET ACTIVITY</small><h3>{activity.bank_name} · {activity.observation_date}</h3></div><span>#{activity.mnemonic}</span></header>
    <div className="market-overview-metrics">{Object.entries(activity.metrics).map(([key, value]) => <article key={key}><small>{labels[key][0]}</small><strong>{number(value)}</strong><span>{labels[key][1]}</span></article>)}</div>
    <footer><span>{activity.series_origin === "stored_snapshots" ? "Auditable local snapshots" : "Official historical series"}</span>{activity.source_url && <a href={activity.source_url} target="_blank" rel="noreferrer">Open official history ↗</a>}</footer>
  </section>;
}

function MarketNoticeAnswer({ data }) {
  return <section className="market-notice"><small>MYFINANCE · MARKET WATCH</small><h3>{data.title ?? "Market data unavailable"}</h3><p>{data.message}</p><small className="general-note">The chat did not substitute a value from a financial report.</small></section>;
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
  const [marketHealth, setMarketHealth] = useState(null);

  useEffect(() => {
    let active = true;
    const refresh = () => fetch(API + "/api/market/collection-health")
      .then((response) => response.ok ? response.json() : null)
      .then((body) => { if (active && body) setMarketHealth(body); })
      .catch(() => {});
    refresh();
    const interval = window.setInterval(refresh, 60_000);
    return () => { active = false; window.clearInterval(interval); };
  }, []);

  async function analyse(nextQuestion = question) {
    if (!nextQuestion.trim()) return;
    const courtesy = courtesyResponse(nextQuestion);
    if (courtesy) {
      setQuestion("");
      setMessages((current) => [...current, { role: "user", text: nextQuestion }, { role: "assistant", type: "courtesy", text: courtesy }]);
      return;
    }
    setQuestion("");
    const turnId = crypto.randomUUID();
    setMessages((current) => [...current, { id: turnId, role: "user", text: nextQuestion }]);
    setLoading(true);
    try {
      const response = await fetch(API + "/api/conversation/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: nextQuestion, context: dossier }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error("conversation unavailable");
      const completedDocumentDossier = body.type === "document" && dossier.mode === "document"
        && (!dossier.bank_id || !dossier.reporting_year);
      const continuedDocumentDossier = body.type === "document" && dossier.mode === "document"
        && !completedDocumentDossier;
      const applied = completedDocumentDossier
        ? `Context completed · ${body.context.bank_name} · ${body.context.reporting_year}`
        : continuedDocumentDossier
          ? `Analysis continued · ${body.context.bank_name} · ${body.context.reporting_year}`
          : "";
      if (applied) {
        setMessages((current) => current.map((message) => (
          message.id === turnId ? { ...message, applied } : message
        )));
      }
      setDossier(body.context ?? dossier);
      if (body.type === "clarification") {
        setMessages((current) => [...current, { role: "assistant", type: "clarification", text: body.message }]);
        return;
      }
      if (body.type === "document") {
        setMessages((current) => [...current, { role: "assistant", type: "document", data: body }]);
        return;
      }
      if (body.type === "comparison") {
        setMessages((current) => [...current, { role: "assistant", type: "comparison", data: body }]);
        return;
      }
      if (body.type === "comparison_analysis") {
        setMessages((current) => [...current, { role: "assistant", type: "comparison_analysis", data: body }]);
        return;
      }
      if (body.type === "multi_metric_comparison_analysis") {
        setMessages((current) => [...current, { role: "assistant", type: "multi_metric_comparison_analysis", data: body }]);
        return;
      }
      if (body.type === "source_value") {
        setMessages((current) => [...current, { role: "assistant", type: "source_value", data: body }]);
        return;
      }
      if (body.type === "metric_analysis") {
        setMessages((current) => [...current, { role: "assistant", type: "metric_analysis", data: body }]);
        return;
      }
      if (body.type === "general") {
        setMessages((current) => [...current, { role: "assistant", type: "general", data: body }]);
        return;
      }
      if (body.type === "market_status") {
        setMessages((current) => [...current, { role: "assistant", type: "market_status", data: body }]);
        return;
      }
      if (body.type === "market_quote") {
        setMessages((current) => [...current, { role: "assistant", type: "market_quote", data: body }]);
        return;
      }
      if (body.type === "market_comparison") {
        setMessages((current) => [...current, { role: "assistant", type: "market_comparison", data: body }]);
        return;
      }
      if (body.type === "market_overview") {
        setMessages((current) => [...current, { role: "assistant", type: "market_overview", data: body }]);
        return;
      }
      if (body.type === "market_performance") {
        setMessages((current) => [...current, { role: "assistant", type: "market_performance", data: body }]);
        return;
      }
      if (body.type === "market_notice") {
        setMessages((current) => [...current, { role: "assistant", type: "market_notice", data: body }]);
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
  function startNewAnalysis() {
    setQuestion("");
    setMessages([]);
    setDossier({ mode: "idle", bank_id: null, bank_name: null, reporting_year: null, topic: null, metric_id: null });
  }
  const contextSummary = dossier.mode === "comparison"
    ? ["Comparative analysis", dossier.metric_id && (metricLabels[dossier.metric_id] ?? dossier.metric_id.replaceAll("_", " ")), dossier.reporting_year].filter(Boolean).join(" · ")
    : dossier.mode === "document"
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
      <nav><button className={view === "analysis" ? "active" : ""} onClick={() => setView("analysis")}>◈ Analysis</button><button className={view === "sources" ? "active" : ""} onClick={() => setView("sources")}>⌘ Sources</button><button className={view === "universe" ? "active" : ""} onClick={() => setView("universe")}>◌ Banks</button></nav>
      <div className="verified-rail"><i /> SOURCE-LOCKED REPORTS<small>5 BANKS · 2021 — 2025</small></div>
    </aside>
    <section className="work">
      <header><span>MYFINANCE 6.5 <i /> Retail banking</span><span><b /> OFFICIAL REPORTS <strong>25</strong></span></header>
      <div className={"content view-" + view} id="analysis">
        <p className="eyebrow">FINANCIAL INTELLIGENCE / TUNISIA</p>
        <h1>Clear answers.<br/><em>Immediate evidence.</em></h1>
        <p className="lead">Explore financial statements with an analyst’s discipline. The conversation retains only confirmed context — bank, year and metric — and every answer remains linked to its official report.</p>
        <section className="panel conversation">
          <div className="panel-title"><span>01</span><div><b>Analysis conversation</b><small>{pendingSummary ? `Clarification needed · ${pendingSummary}` : contextSummary ? `Current context · ${contextSummary}` : "No context retained yet"}</small></div><button className="new-analysis" onClick={startNewAnalysis} disabled={loading}>NEW ANALYSIS</button><mark>● SOURCE-LOCKED</mark></div>
          {(messages.length > 0 || loading) && <div className="thread" aria-live="polite">
            {messages.map((message, index) => <div className={`message ${message.role} ${message.type ?? ""}`} key={message.id ?? index}>
               {message.role === "user" ? <><small>YOU</small><p>{message.text}</p>{message.applied && <em>Applied context: {message.applied}</em>}</> : message.type === "numeric" ? <><small>MYFINANCE · AUTOMATICALLY VALIDATED VALUE</small><div className="result"><div className="value"><small>{metricLabels[message.data.metric_id] ?? message.data.metric_id.replaceAll("_", " ")}</small><strong>{number(message.data.value)}</strong><p>{message.data.unit_scale === "thousand" ? "thousand TND" : message.data.currency} · financial year {message.data.reporting_year}</p></div><article><div><small>PRIMARY EVIDENCE</small><b>PAGE {message.data.page_number}</b></div><blockquote>“{message.data.source_excerpt}”</blockquote><footer><em>PDF</em>{message.data.source_document.split("/").pop()} <button onClick={() => openDocument(message.data.source_document)}>View source ↗</button></footer></article></div></> : message.type === "comparison" ? <ComparisonAnswer data={message.data} openDocument={openDocument} /> : message.type === "comparison_analysis" ? <ComparisonAnalysisAnswer data={message.data} openDocument={openDocument} /> : message.type === "multi_metric_comparison_analysis" ? <MultiMetricComparisonAnalysisAnswer data={message.data} openDocument={openDocument} /> : message.type === "source_value" ? <SourceValueAnswer data={message.data} openDocument={openDocument} /> : message.type === "metric_analysis" ? <MetricAnalysisAnswer data={message.data} /> : message.type === "document" ? <DocumentAnswer data={message.data} openDocument={openDocument} /> : message.type === "general" ? <GeneralAnswer data={message.data} /> : message.type === "market_status" ? <MarketStatusAnswer data={message.data} /> : message.type === "market_quote" ? <MarketQuoteAnswer data={message.data} /> : message.type === "market_comparison" ? <MarketComparisonAnswer data={message.data} /> : message.type === "market_overview" ? <MarketOverviewAnswer data={message.data} /> : message.type === "market_performance" ? <MarketPerformanceAnswer data={message.data} /> : message.type === "market_activity" ? <MarketActivityAnswer data={message.data} /> : message.type === "market_notice" ? <MarketNoticeAnswer data={message.data} /> : <><small>MYFINANCE</small><p>{message.text}</p></>}
            </div>)}
            {loading && <div className="message assistant pending"><small>MYFINANCE</small><p>Checking the relevant official source…</p></div>}
          </div>}
          <div className="composer"><textarea aria-label="Your question" placeholder="Write your question or a follow-up…" value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); analyse(); } }} /><button onClick={() => analyse()} disabled={loading}>{loading ? "ANALYSING…" : "SEND"} <b>↗</b></button></div>
          <div className="suggest"><span>TRY</span>{examples.map((item) => <button key={item} onClick={() => analyse(item)}>{item}</button>)}</div>
        </section>
        <section className="universe" id="universe"><div><span>BANKING UNIVERSE</span><h2>Banks on the radar.</h2><p>All five banks and their 2021–2025 reports are available. Each of the 174 displayed facts has been automatically validated; Zitouna 2021 deliberately has no net-income value.</p></div><div className="bank-grid">{banks.map(([name, state]) => <article className="ready" key={name}><b>{name}</b><mark>{state}</mark><small>05 reports · 2021 — 2025</small></article>)}</div></section>
        <section className="sources" id="sources"><div><span>SOURCE REGISTER</span><h2>Every answer can be audited.</h2><p>Every value retains its official report, page number and source excerpt.</p><CollectionHealth health={marketHealth} /></div><dl><div><dt>25</dt><dd>official reports</dd></div><div><dt>5</dt><dd>banks in the corpus</dd></div><div><dt>2021—25</dt><dd>available period</dd></div></dl></section>
      </div>
    </section>
  </main>;
}
createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);
