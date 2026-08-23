# Contribution and Delivery Workflow

## Architecture boundary

MyFinance is organised by responsibility: `chat/` serves the user, `autotest/` verifies behaviour, `shared/` carries contracts and `data/` holds evidence and validated facts. The two applications communicate through local APIs and shared contracts, not through one another’s UI code.

## Safe change workflow

1. State the user need or risk intent and write an acceptance criterion.
2. Change the smallest responsible layer: contract, source validation, orchestration, interface or test scenario.
3. Add or adapt the deterministic regression test.
4. Run `uv run ruff check .`, `uv run pytest -q` and the build for every changed web application.
5. Exercise the real Testing journey when the change affects the Chat, Groq integration, campaign flow or reporting.
6. Update the relevant guide and add a durable architectural decision to `docs/decision-log.md` when appropriate.

## Non-negotiable quality rules

- No financial value is added without an `auto_validated` fact and official PDF evidence.
- No API key, generated campaign trace or browser artefact is committed. `.env`, `data/autotest/` and Playwright output remain ignored.
- Scripts under `chat/scripts/` and `autotest/scripts/` stay explicit and reproducible; they must not become hidden API-startup work.
- Any deletion under `data/` requires explicit review: source PDFs and corpus content are business evidence.
- A provider failure must be labelled as a provider failure, not disguised as a factual Chat result.

Read the [Developer guide](docs/developer-guide.md) before changing application behaviour and the [Operations guide](docs/operations-guide.md) before changing runtime configuration.
