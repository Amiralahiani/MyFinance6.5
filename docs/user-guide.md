# User Guide — Financial Chat and Testing Lab

## 1. What MyFinance is for

MyFinance helps an analyst navigate a controlled collection of official Tunisian bank reports. It is designed for questions that must be reviewed later: a financial metric, a comparison, a report explanation or a current official share price.

It does **not** estimate missing figures, give investment advice, access personal bank accounts or treat a general web answer as evidence.

## 2. Asking effective questions

For a financial metric, include three elements whenever possible:

```text
[bank] + [metric] + [reporting year]
```

| Goal | Good question |
| --- | --- |
| Retrieve a value | `What is BIAT's net banking income in 2023?` |
| Compare banks | `Compare BIAT and Banque de Tunisie's net income in 2023.` |
| Ask about a report note | `What does BIAT's 2021 report say about related-party transactions?` |
| Ask about current market data | `What is BIAT's current share price?` |
| Compare current prices | `Compare BIAT, BT and Amen Bank's current share prices.` |

MyFinance understands common French and English financial terms, including *PNB / net banking income*, *net income* and *customer deposits*. It may repair an obvious typo, but it does not rewrite a request in a way that changes its scope.

## 3. Reading each response type

### Automatically validated value

This is the strongest response type. It contains:

- the metric label and reported number;
- reporting year, unit and currency;
- an official PDF page;
- the exact source excerpt that supports the value.

For example, a PNB answer is reported in `thousand TND` when that is the unit in the bank’s published financial statements. Do not compare values with different units without normalising them first.

### Comparison view

A comparison is available only when the requested values are compatible. The view ranks banks and shows the range and ratio, while keeping the number of primary sources visible.

If a bank is not supported, MyFinance names the unknown bank instead of silently dropping it from the comparison.

### Documentary answer

A documentary answer explains a subject in the report, such as a risk policy, a related-party transaction or a portfolio category. It provides source excerpts and page links. It should be read as an explanation of the cited report, not as a numeric fact unless the response is explicitly labelled as an automatically validated value.

### Market Watch

Market answers are separate from annual-report answers. A current quote includes the displayed price, session movement, ticker, ISIN, capture time and the official Market Watch link. The quote may be delayed by the exchange; MyFinance displays that delay instead of hiding it.

### Clarification or refusal

MyFinance asks a clarification when a safe answer needs more scope. Examples:

| What is missing | What to add |
| --- | --- |
| Metric | `net banking income`, `net income` or `customer deposits` |
| Year | `in 2023` |
| Comparison criterion | `current share prices` or `net income in 2024` |
| Supported bank | Use the full bank name or a recognised listed-bank ticker |

A clarification is not a failed answer. It prevents an answer from being attached to the wrong bank, year or metric.

## 4. Conversation context: what is remembered

The Chat keeps only useful, explicit context.

| You say | Then you can say | Why it is safe |
| --- | --- | --- |
| `Banque Zitouna` | `What is its PNB in 2023?` | The bank is selected, but no reporting year is assumed |
| `What is BIAT's current share price?` | `Compare BIAT, BT and Amen Bank.` | The active context is current market data |
| `What is BIAT's PNB in 2023?` | `And net income?` | The bank and year remain explicit in the safe metric context |

The Chat deliberately does not carry a previous answer into an unknown bank name, a different market period or an unrelated report topic.

## 5. Use the Testing Lab

Open <http://localhost:3001> after the stack starts.

### Release validation

Use **Run full validation** before a demonstration or release. It replays the catalogue of financial facts and behavioural contracts through the Chat API and, where applicable, the web interface. It is reproducible and does not depend on Groq for its verdict.

### AI exploration

Use **Explore with Groq** to look for additional edge cases. These questions are intentionally separated from the release catalogue. If Groq is unavailable, the dashboard tells you why; it does not mislabel the problem as a Chat failure.

### Visual check

Use **Start check** in the Chat visual check card to run live Playwright journeys. The Testing dashboard shows progress and logs. Open <http://localhost:6080> to watch the browser click, type, wait for responses and scroll through the resulting answer.

### Campaign control

You can stop a running campaign. A stopped release campaign can be resumed from its history row; campaigns can also be deleted. The history is local to `data/autotest/` and does not change financial source data.

## 6. If something looks wrong

| You see | Meaning | Next action |
| --- | --- | --- |
| `Official quote unavailable` | Market Watch could not be read safely | Check the collector/official site; do not substitute a report value |
| `Qdrant ready` but a documentary answer is weak | Semantic retrieval is available, not a guarantee of a matching passage | Use a more precise report topic or page/note name |
| `Embeddings degraded` | Qdrant enrichment is unavailable | Lexical retrieval and validated financial facts still work |
| `Groq quota or provider limit` | Optional AI generator/critic could not use the configured key | Check `.env`, recreate the relevant container and retry later |
| `Completed with execution issue` | At least one campaign request had a transport issue | Open the executor stage; completed responses remain inspectable |

For setup and maintenance, see the [Operations guide](operations-guide.md). For the evidence system behind the interface, see the [Architecture](architecture.md).
