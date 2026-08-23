# Financial Fact States

```text
Official PDF → in-memory extraction → deterministic validation → auto_validated | rejected
```

- `auto_validated/` contains the only values that may be returned in a financial response.
- `validation-runs/<bank>/<year>/rejected_facts.json` retains candidates rejected by one or more checks and their reasons.

The Chat never promotes a rejected candidate, raw OCR text or an evidence chunk to a financial value. See [the data model](../../../docs/data-model.md) for the provenance chain.
