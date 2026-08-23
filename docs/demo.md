# Demonstration Guide

## Demo objective

Demonstrate that MyFinance is not simply answering financial questions: it retrieves controlled evidence, refuses weak scope, enriches documentary research without replacing sources, separates current market data from reports and proves the product through an independent Testing Lab.

## 1. Prepare the environment

From the repository root, with Docker Desktop running:

```powershell
Copy-Item .env.example .env
.\scripts\myfinance.ps1 start
```

Open these tabs before the audience arrives:

| Tab | Address |
| --- | --- |
| Financial Chat | <http://localhost:3000> |
| Agentic Testing Lab | <http://localhost:3001> |
| Live Playwright viewer | <http://localhost:6080> |

Run `.\scripts\myfinance.ps1 status` first if you need to verify containers and the last market-collector events.

## 2. Recommended 10-minute flow

### Moment 1 — a validated financial fact

Ask:

```text
What is the PNB of BIAT in 2023?
```

Show the number, `thousand TND` unit, financial year, primary PDF page and the quoted source line. Explain that the value comes from the `auto_validated` catalogue, not from a generated summary.

### Moment 2 — a controlled comparison

Ask:

```text
Compare the PNB of BIAT and Banque Zitouna in 2023.
```

Show the rank, range, ratio and number of primary sources. The important point is that the comparison is created only from compatible facts, not by asking an LLM to judge two reports.

### Moment 3 — a documentary answer

Ask:

```text
What does BIAT's 2021 report say about related-party transactions?
```

Open the excerpts. Explain that this is not rendered as a numeric fact: it is a source-grounded interpretation of pages in the official report. Qdrant may help locate the passage, but the citations remain page-level and reviewable.

### Moment 4 — a safe clarification

Ask:

```text
Compare BIAT, BT and Amen Bank.
```

The Chat asks which criterion should be compared. Follow with:

```text
current share prices
```

Show that the named-bank list is retained as a safe market context, then that every quote is labelled as Market Watch data rather than a report value.

### Moment 5 — a current official quote

Ask:

```text
What is BIAT's current share price?
```

Point out the price, session change, ticker, ISIN, capture timestamp, delay notice and official market link. This demonstrates that current market data is isolated from the annual-report pipeline.

### Moment 6 — prove the product with the Testing Lab

Open <http://localhost:3001> and show:

1. **Live stack state**: Chat API, Qdrant, embeddings and market collector health.
2. **Run full validation**: reproducible financial facts and API ↔ Web contracts.
3. **Campaign timeline**: catalogue, planner, executor, evaluator, optional critic and reporter.
4. **Scenario detail**: raw response, latency, evaluator rules and source comparison.
5. **Visual check**: start it, then open port `6080` to watch the real Chat browser type, receive an answer and scroll the page.

If Groq is configured, also show **AI exploration**. Make clear that it generates potential edge cases, while release validation remains deterministic and reproducible.

## 3. Key messages for each audience

| Audience | Message to emphasise |
| --- | --- |
| Business reviewer | Every published number links back to an official report line |
| Risk/compliance reviewer | Clarification and abstention are designed outcomes, not silent product gaps |
| Technical reviewer | RAG is additive, Qdrant is optional and the state machine remains deterministic |
| Product reviewer | Chat experience and testing experience are separate, visible applications |
| Management | The system demonstrates controlled retrieval, transparent market data and repeatable quality evidence |

## 4. What not to claim

- Do not describe the project as an investment-advice engine.
- Do not claim support for a bank, metric, year or share-price history outside the configured corpus and market mapping.
- Do not treat a Groq response as a financial source.
- Do not show a stale market snapshot as a live price.
- Do not call Qdrant a replacement for the official reports.

## 5. Demo recovery

| Problem | Recovery |
| --- | --- |
| A market quote is unavailable | Explain the explicit availability notice; use a validated annual-report question instead |
| Groq quota/key problem | Run release validation and show deterministic checks; AI exploration is optional |
| Qdrant is degraded | Demonstrate numeric facts and lexical documentary retrieval; explain the safe fallback |
| A long-running campaign is no longer useful | Stop it from the campaign detail, then inspect or clean it in history |
| Docker service is not reachable | Run `.\scripts\myfinance.ps1 status` and inspect the relevant container logs |

For full setup instructions, see the [Operations guide](operations-guide.md). For a user-facing explanation of response types, see the [User guide](user-guide.md).
