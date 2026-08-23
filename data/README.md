# MyFinance Data

This directory keeps source material, normalised evidence and approved financial facts separate. A number is never its own source: the official PDF remains the primary evidence.

```text
data/
├── raw/official-reports/etat financier/<bank>/<report>.pdf
├── reference/financial_metrics.json
├── normalized/
│   ├── corpus/<bank>/<year>/
│   │   ├── documents.json
│   │   └── evidence_chunks.jsonl
│   └── facts/
│       └── auto_validated/<bank>/<year>/financial_facts.json
├── validation-runs/<bank>/<year>/
│   ├── report.json
│   └── rejected_facts.json
├── market-snapshots/
└── autotest/
```

## Source and evidence layers

| Location | Contains | May produce a numeric Chat answer? |
| --- | --- | --- |
| `raw/` | Immutable official reports | No; it is the primary source |
| `reference/` | Versioned metric, bank, general-source and market policies | No; definitions never hold annual values |
| `normalized/corpus/` | Page-bounded transcription and PDF provenance | No; documentary evidence only |
| `normalized/facts/auto_validated/` | Approved, normalised financial facts | Yes |
| `validation-runs/` | Validation decisions and rejected candidates | No |
| `market-snapshots/` | Dated official Market Watch observations | Only for explicitly labelled market responses |
| `autotest/` | Local campaign state, reports and execution evidence | No |

## Reading rules

1. Official PDFs are never modified by the application.
2. Every evidence chunk remains inside one PDF page and keeps bank, year, page and document hash metadata.
3. Only `auto_validated` facts can reach a financial value or comparison response.
4. Rejected candidates remain traceable but are never shown as facts.
5. Runtime artefacts and secrets are excluded from Git.

For the controlled extension procedure, see [Data coverage and onboarding](../docs/data-coverage.md). For the exact object model, see [Evidence and data model](../docs/data-model.md).
