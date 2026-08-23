# Data Coverage and Onboarding

## 1. Current controlled scope

MyFinance currently contains individual financial reports for five Tunisian banks from 2021 through 2025.

| Bank | Identifier | Reports |
| --- | --- | --- |
| Amen Bank | `amen_bank` | 2021–2025 |
| Attijari Bank | `attijari_bank` | 2021–2025 |
| BIAT | `biat` | 2021–2025 |
| Banque de Tunisie | `bt` | 2021–2025 |
| Banque Zitouna | `zitouna` | 2021–2025 |

The active target is 25 reports, 175 expected bank/year/metric cells and 175 `auto_validated` facts. The measured coverage must come from files, not from a manually maintained claim:

```powershell
uv run python chat/scripts/audit_fact_coverage.py
```

Use strict mode before a release when the current coverage matrix is the intended contractual scope:

```powershell
uv run python chat/scripts/audit_fact_coverage.py --strict
```

The command returns a non-zero exit code when an expected cell is missing.

## 2. What is covered by a fact

The fact catalogue contains the comparable financial metrics defined in `data/reference/financial_metrics.json`. A valid fact is not only a number. It includes its official label, reporting year, currency, unit scale, scope, source PDF, page and source excerpt.

| Source state | Can the Chat show it as a financial value? | Meaning |
| --- | --- | --- |
| Official PDF | No, not directly | Primary source material |
| Corpus chunk | No, not by itself | Page-level documentary evidence |
| Candidate | No | Extracted possibility still awaiting validation |
| `auto_validated` fact | Yes | Deterministically checked published value |
| Rejected candidate | No | Preserved validation evidence for review |

This distinction prevents OCR fragments, prose paragraphs or an LLM guess from becoming a reported financial number.

## 3. Source-data layout

```text
data/
├── raw/official-reports/etat financier/<bank>/   immutable source PDFs
├── normalized/corpus/<bank>/<year>/               page-level evidence chunks
├── normalized/facts/auto_validated/               approved financial facts
├── validation-runs/                               accepted/rejected extraction traces
├── reference/                                     metric, bank, source and market policies
├── market-snapshots/                              dated official market observations
└── autotest/                                      local campaign state and reports
```

Read-only source data is mounted into the Chat and Testing containers. Runtime artefacts such as campaigns and market snapshots are written locally but are excluded from Git.

## 4. Procedure: add a new official report

Follow the sequence; do not jump directly to a Chat response or vector index.

1. **Acquire the PDF from an official source.** Save it under `data/raw/official-reports/etat financier/<bank>/` with a name that makes bank and reporting year unambiguous.
2. **Record its identity.** Ingestion creates or verifies the document record, including SHA-256 and page count.
3. **Extract page-level corpus.** Every evidence chunk stays within one PDF page and retains bank, year, page and source metadata.
4. **Review metric definitions.** Confirm the existing metric’s label, unit, scope and synonyms in `data/reference/financial_metrics.json`. Add a definition if this is genuinely a new metric; never add annual values to the definition file.
5. **Run candidate extraction and deterministic validation.** Ambiguous value, wrong scope, incompatible unit, duplicate match or accounting inconsistency must result in rejection.
6. **Inspect the evidence manually.** Confirm the exact published line, PDF page, unit, comparison column and scope before accepting it as `auto_validated`.
7. **Add tests.** Add a focused value, comparison or behavioural test that proves the new supported fact can be retrieved safely.
8. **Reindex only after corpus changes.** Rebuild Qdrant after the approved corpus/facts change:

   ```powershell
   .\scripts\myfinance.ps1 reindex
   ```

9. **Run the quality gates.** Execute Ruff, the Python suite and the relevant release validation.

## 5. Procedure: add a new metric

Adding a metric is a semantic change, not simply another field name.

| Step | Required decision |
| --- | --- |
| Name | Stable `metric_id` and user-facing English/French labels |
| Synonyms | Accepted vocabulary, including PNB-style local terminology where appropriate |
| Source statement | Financial-statement section and expected official label |
| Scope | Individual vs consolidated, gross vs net, balance vs flow |
| Unit | Currency and scale expected in source reports |
| Validation | Uniqueness, period and reconciliation rules needed before approval |
| Presentation | How a numeric response and comparison will describe the value |

Do not expose a metric in the user interface before the evidence and validation model exists.

## 6. Qdrant indexing lifecycle

Qdrant indexes evidence chunks; it does not validate facts. Reindex after changing a source PDF, the normalised corpus or approved metadata that affects retrieval. Do not reindex merely because a document question received a clarification.

| Situation | Action |
| --- | --- |
| New or corrected source corpus | Reindex |
| Existing vectors already present, no corpus change | Do nothing |
| Qdrant unavailable | Use lexical retrieval while repairing local infrastructure |
| Ollama model absent | Pull `nomic-embed-text`, then re-run the one-shot indexer |

## 7. Market instrument coverage

The official Market Watch mapping is held separately in `data/reference/market_instruments.json`.

| Instrument | Current mapping state |
| --- | --- |
| Amen Bank | Mapped |
| Attijari Bank | Mapped |
| BIAT | Mapped |
| Banque de Tunisie | Mapped |
| Banque Zitouna | Explicitly `not_mapped` |

`not_mapped` is intentional. The Chat must explain that an official instrument cannot be matched rather than guessing a ticker or displaying a quote from another entity.

## 8. Review checklist

Before treating an extension as complete, verify:

- [ ] The original PDF is present and traceable.
- [ ] Bank, year and report perimeter are unambiguous.
- [ ] Every displayed number is `auto_validated`.
- [ ] Page, excerpt, scale and currency are attached.
- [ ] A neighbouring year/bank does not accidentally satisfy the lookup.
- [ ] Unknown, missing or unsupported scope produces clarification rather than fallback.
- [ ] New corpus content is in Qdrant only after validation.
- [ ] Focused tests and the full suite pass.

See the [Data model](data-model.md) for the object relationships and the [Developer guide](developer-guide.md) for the implementation path.
