# MyFinance Documentation

> A guided view of the product, its evidence rules and the engineering that keeps every answer reviewable.

The documentation is organised as reading routes, not as a flat list of technical notes. Start with the route that matches your role, then follow the cross-links when you need more depth.

## Choose your route

| If you are… | Start here | Then read |
| --- | --- | --- |
| Discovering the product | [Project README](../README.md) | [User guide](user-guide.md) and [Demo guide](demo.md) |
| Reviewing trust and evidence | [Architecture](architecture.md) | [Data model](data-model.md) and [Data coverage](data-coverage.md) |
| Running the local stack | [Operations guide](operations-guide.md) | [Security and deployment](security-and-deployment.md) |
| Extending the project | [Developer guide](developer-guide.md) | [Contribution guide](../CONTRIBUTING.md) |
| Validating a release | [Agentic Testing README](../autotest/README.md) | [Demo guide](demo.md) and [Operations guide](operations-guide.md) |

## Documentation map

### Product and demonstration

| Document | Purpose |
| --- | --- |
| [Project README](../README.md) | Product overview, fast local start, trust model and repository map |
| [User guide](user-guide.md) | How to ask questions, read evidence, compare banks and understand safe clarifications |
| [Demo guide](demo.md) | A repeatable presentation of the Chat, RAG, market data and Testing Lab |

### Architecture and data

| Document | Purpose |
| --- | --- |
| [Architecture](architecture.md) | System boundaries, answer paths, RAG design, testing workflow and failure behaviour |
| [Data model](data-model.md) | PDF, corpus, evidence chunk, financial fact, market snapshot and campaign artefacts |
| [Data coverage](data-coverage.md) | Current coverage and the controlled procedure for adding reports or metrics |

### Operations and engineering

| Document | Purpose |
| --- | --- |
| [Operations guide](operations-guide.md) | Docker lifecycle, environment configuration, Qdrant, Ollama, collector and troubleshooting |
| [Security and deployment](security-and-deployment.md) | Local security defaults and requirements before Internet exposure |
| [Developer guide](developer-guide.md) | Code map, contracts, test strategy and safe change workflow |

## Documentation promises

Every guide follows four rules:

1. **Runtime truth wins.** Commands and paths describe the active Docker Compose and PowerShell scripts.
2. **Evidence is distinguished from assistance.** PDFs and validated facts are authorities; Qdrant and Groq are supporting mechanisms.
3. **Failure behaviour is documented.** A missing service must produce a known fallback or an explicit notice.
4. **Secrets never appear in examples.** Use `.env` locally; do not put real API keys in Markdown, source code, reports or screenshots.

## Quick glossary

| Term | Meaning in MyFinance |
| --- | --- |
| **Official PDF** | Primary source document stored in the local corpus |
| **Evidence chunk** | One page-bounded extract with provenance metadata |
| **`auto_validated` fact** | The only data type allowed to produce a financial number in the Chat |
| **Hybrid RAG** | Lexical retrieval enriched by optional Qdrant vector retrieval over the same evidence chunks |
| **Market snapshot** | Dated observation captured from the official Market Watch source |
| **Release validation** | Reproducible catalogue and cross-channel checks, independent from AI exploration |
| **AI exploration** | Optional Groq-generated edge cases, kept separate from release truth |
