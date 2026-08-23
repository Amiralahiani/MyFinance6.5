# Reference Policies

The files in this directory define meaning and routing policy. They must not contain annual financial values copied from a report.

| File family | Responsibility |
| --- | --- |
| `financial_metrics.json` | Supported metric definitions, labels, synonyms, statement location, scale and validation expectations |
| Bank definitions | Supported banks, aliases and user-facing names |
| General sources | Curated official sources allowed for sourced general explanations |
| Market instruments and sources | Official Market Watch mapping and source policy |
| Documentary glossary | Bilingual bridges between user wording and official report terminology |

The shared profile currently covers seven comparable metrics over the individual 2021–2025 reports of Amen Bank, Attijari Bank, BIAT, Banque de Tunisie and Banque Zitouna. The measured target is 175 approved facts across 175 expected cells.

A metric marked as supported may be recognised in a user request, but it can be displayed only when a matching `auto_validated` fact exists under `data/normalized/facts/`. A missing or ambiguous metric remains unavailable until an official PDF line supports deterministic extraction and validation.

See [Data coverage](../../docs/data-coverage.md) before editing this directory.
