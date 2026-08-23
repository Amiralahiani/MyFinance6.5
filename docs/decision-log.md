# Decision Log

This log records the decisions that shape the active MyFinance system. It is not a changelog; it explains why the project behaves the way it does.

## 2026-07-17 — Evidence-first scope

**Decision:** MyFinance focuses on controlled analysis of bank financial reports over a defined period.

**Rationale:** The project is valuable only if a reviewer can trace an answer to an official document. Broad, unsourced financial conversation would weaken that objective.

**Consequence:** The Chat clarifies or abstains when the requested bank, year, metric or evidence is not supported.

## 2026-07-17 — Numeric values require deterministic approval

**Decision:** Only `auto_validated` facts may produce a financial number.

**Rationale:** OCR, report prose, embeddings and model output can be useful signals but are not sufficient evidence of a published figure.

**Consequence:** Candidate values and documentary chunks remain separate from numeric responses.

## 2026-08-23 — Hybrid RAG enriches, never replaces, lexical evidence

**Decision:** Add Qdrant and local Ollama embeddings as an optional hybrid retrieval path.

**Rationale:** Semantic search improves recall for documentary questions whose wording differs from a PDF, while the existing page-level corpus remains authoritative.

**Consequence:** If Qdrant or Ollama is unavailable, MyFinance uses lexical retrieval and still preserves safe answer behaviour.

## 2026-08-23 — Market data is a separate evidence domain

**Decision:** Current share prices use official Market Watch reading and dated snapshots, not annual-report data.

**Rationale:** A share price is time-sensitive and must not be substituted by a balance-sheet value or an old report disclosure.

**Consequence:** Market responses visibly include source, capture time and delay; unavailable market data produces an explicit notice.

## 2026-08-23 — Conversation context is narrow and explicit

**Decision:** The Chat retains only unambiguous bank, metric, year and market/comparison selections.

**Rationale:** Overly broad memory can attach a new question to the wrong source or reuse an old reporting year.

**Consequence:** Plain bank selection does not assume a report year; unknown banks cannot inherit an active comparison; incomplete comparisons ask for a criterion.

## 2026-08-23 — Testing is a separate product surface

**Decision:** Build a standalone Agentic Testing Lab rather than hide tests behind the Chat.

**Rationale:** Product quality is easier to review when scenario generation, execution evidence, deterministic evaluation and reporting are visible to a user.

**Consequence:** The dashboard can replay release contracts, inspect API/Web agreement, display Playwright and keep AI exploration separate from reproducible validation.

## 2026-08-23 — Groq is optional and non-authoritative

**Decision:** Use Groq for optional source-grounded wording, exploration and critique, never as a fact source or final deterministic verdict.

**Rationale:** External-provider availability, key validity and quotas must not determine whether an approved financial fact is correct.

**Consequence:** Provider errors are reported as provider errors. Core Chat safety and deterministic release validation remain available.

## 2026-08-23 — Local-first runtime

**Decision:** Bind Docker services to localhost by default and provide a PowerShell operational helper.

**Rationale:** The project is intended for local development and internal demonstration; its internal services should not accidentally become network-accessible.

**Consequence:** Public deployment requires an explicit security architecture with HTTPS, authentication, shared rate limiting and private data services.
