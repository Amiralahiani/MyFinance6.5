# MyFinance Chat

The Chat is the evidence-first user application. It turns a question into one of five explicit outcomes: a validated value, comparison, documentary explanation, official market answer or clarification.

## Responsibilities

| Area | Responsibility |
| --- | --- |
| `api/` | FastAPI routes, request safety, assessment, conversation state and response contracts |
| `knowledge/` | Official PDFs, corpus, validated facts, lexical retrieval and optional Qdrant adapter |
| `market/` | Official Market Watch reading, mappings, snapshots and freshness |
| `web/` | React interface, typed response rendering and Playwright journeys |
| `scripts/` | Explicit entry points for API, data audit, vector indexing and market collection |
| `tests/` | Domain, API, routing, evidence and market regression tests |

## Response contract

| Situation | Required behaviour |
| --- | --- |
| Matching approved fact | Show number, unit, year, source PDF, page and excerpt |
| Compatible multi-bank request | Show a comparison only from compatible approved facts |
| Documentary topic | Explain retrieved evidence and retain pages/source references |
| Current market request | Show official quote data with capture time and source link |
| Missing/unsafe scope | Ask the minimal clarification or abstain clearly |

## Local development

```powershell
# Chat API: http://127.0.0.1:8000
uv run python chat/scripts/run_orchestrator.py

# Chat Web: http://127.0.0.1:3000
Set-Location chat/web
npm install
npm run dev:chat
```

Run the real browser journeys:

```powershell
Set-Location chat/web
npm run test:e2e
```

For Docker, RAG, collector and targeted rebuild instructions, use the [Operations guide](../docs/operations-guide.md). For code-level responsibilities, use the [Developer guide](../docs/developer-guide.md).

## Optional Groq assistance

Groq can provide source-grounded wording and supports the Testing Lab’s AI exploration. It receives only selected local evidence for applicable tasks. It cannot choose a numeric fact, bypass a source rule or convert an unsupported answer into a reported value.

Configure it only through `.env` or the process environment. Never commit a real key.
