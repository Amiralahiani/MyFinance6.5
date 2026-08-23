# MyFinance Agentic Testing Lab

The Testing Lab independently verifies the Chat through real API requests, optional real web interactions and inspectable campaign reports.

## Campaign flow

<p align="center">
  <img src="../docs/assets/testing-lab-flow.svg" alt="MyFinance Testing Lab campaign flow" width="100%" />
</p>

The Planner and Evaluator are deliberately separate. An AI-generated scenario never directly becomes an unrestricted action, and an AI critic never overrides a deterministic factual verdict.

## Components

| Path | Purpose |
| --- | --- |
| `api/` | FastAPI campaign endpoints, local persistence and SSE events |
| `src/` | Catalogue, planner, executors, evaluator, critic, reports and observability |
| `web/` | React dashboard for campaigns, history, stack health and live Playwright |
| `configs/` | Bounded campaign and provider configuration |
| `scripts/` | Reproducible local entry points |
| `tests/` | Campaign control, provider fallback, system-state and visual-check tests |

## Two different validations

| Validation | Purpose | Groq required? |
| --- | --- | --- |
| **Release validation** | Replays known financial facts, behaviour contracts and API ↔ Web consistency | No for deterministic verdicts |
| **AI exploration** | Generates additional edge cases and asks for confirmation where useful | Yes |

Keeping these paths separate prevents an external provider quota from changing release truth.

## Local development

The Chat API must be reachable first.

```powershell
# Testing API: http://127.0.0.1:8001
uv run python autotest/scripts/run_testing_api.py

# Testing Web: http://127.0.0.1:3001
Set-Location autotest/web
npm install
npm run dev:testing
```

While a Chat Visual Check is running, the Docker Playwright browser can optionally be observed at <http://localhost:6080>. Outside a visual check it may be blank; it is not a separate user application.

## Campaign controls and artefacts

Campaign history, raw events and reports are kept locally under `data/autotest/`. They are excluded from Git and can be deleted through the dashboard without changing the source PDFs or validated facts.

An executor issue is preserved as transport evidence. When a campaign receives some responses but another request fails, the UI shows **Completed with execution issue** rather than presenting it as either a full pass or an unexplained total failure.

For operations and targeted rebuilds, see the [Operations guide](../docs/operations-guide.md). For the full engineering model, see the [Developer guide](../docs/developer-guide.md).
