# Operations Guide — Local Docker Stack

## 1. Purpose and boundary

This guide operates MyFinance on one developer or demonstration workstation. The default Docker configuration publishes application services on `127.0.0.1`, not on the local network or the Internet.

For public deployment requirements, read [Security and deployment](security-and-deployment.md) before changing any port binding or reverse-proxy setting.

## 2. Prerequisites

| Requirement | Check |
| --- | --- |
| Docker Desktop is running | `docker version` |
| Docker Compose is available | `docker compose version` |
| PowerShell is open at the repository root | `Get-Location` |
| Local configuration exists | `Test-Path .env` |

Create the local configuration only once:

```powershell
Copy-Item .env.example .env
```

Do not commit `.env`. Add a real `GROQ_API_KEY` only if you want AI exploration, qualitative evaluation or optional source-grounded wording. The deterministic financial and evidence paths do not depend on that key.

## 3. Recommended lifecycle commands

The PowerShell helper is the normal entry point. It keeps the start sequence in one place and avoids rerunning a vector index that already exists.

```powershell
# First start or normal start
.\scripts\myfinance.ps1 start

# Inspect containers and the latest Market Watch collector events
.\scripts\myfinance.ps1 status

# Rebuild vectors after a corpus/fact change only
.\scripts\myfinance.ps1 reindex

# Stop the local stack cleanly
.\scripts\myfinance.ps1 stop
```

### What `start` does

| Step | Action | Why it exists |
| --- | --- | --- |
| 1 | Builds and starts the local services with the embeddings profile | Brings up Chat, Testing, Qdrant, Ollama and web applications |
| 2 | Pulls `nomic-embed-text` through Ollama | Provides local embeddings for the vector index |
| 3 | Checks Qdrant and indexes only if no vectors exist | Avoids re-embedding unchanged corpus data |
| 4 | Rebuilds the Chat API after the index is available | Lets the Chat see the semantic collection |
| 5 | Starts the Market Watch collector every 30 minutes | Maintains dated official market snapshots |

The initial run is expected to be slower: Docker pulls/builds images, Chromium is installed for official market reading, Ollama downloads the embedding model and Qdrant receives the first vector collection. Later starts should reuse those assets.

## 4. Service map and health checks

| Service | Address | Healthy when |
| --- | --- | --- |
| Chat Web | <http://localhost:3000> | The Chat page loads and can call the API |
| Chat API | <http://localhost:8000/health> | It returns an HTTP success |
| Testing Web | <http://localhost:3001> | The dashboard loads stack health |
| Testing API | <http://localhost:8001/health> | It returns an HTTP success |
| Playwright viewer | <http://localhost:6080> | Optional noVNC observer; useful only while a Chat Visual Check is active |
| Qdrant | <http://localhost:6333> | The collection is reachable; vectors may be zero before indexing |
| Ollama | <http://localhost:11434> | `docker compose exec ollama ollama list` shows `nomic-embed-text` |

Useful diagnostics:

```powershell
docker compose ps
docker compose logs --tail=100 chat-api
docker compose logs --tail=100 testing-api
docker compose logs --tail=30 market-collector
docker compose exec ollama ollama list
```

The Testing dashboard additionally calls its local `system-state` endpoint and displays Chat reachability, Qdrant collection size, embeddings availability and Market Watch freshness.

## 5. When a rebuild is actually needed

Avoid rebuilding the entire stack for every change.

| You changed | Required action |
| --- | --- |
| Chat API Python code | `docker compose up -d --build chat-api` |
| Testing API Python code | `docker compose up -d --force-recreate testing-api` |
| Testing Web React code | `Set-Location autotest/web` then `npm run build`; refresh port `3001` |
| Chat Web React code | `docker compose up -d --build chat-web` |
| Docker Compose / Dockerfile / dependency lockfile | Rebuild the affected service or use `myfinance.ps1 start` |
| Official PDFs, corpus or validated facts | `.\scripts\myfinance.ps1 reindex` after validation |

`testing-api` mounts the local Testing source into its container, but its running Python process still needs recreation after a code change. `testing-web` serves the host `autotest/web/dist` directory, so rebuilding that static bundle is enough for a UI-only change.

## 6. Qdrant and Ollama

Qdrant is optional for correctness. It enriches documentary recall over the same page-level evidence already held locally. Ollama supplies the `nomic-embed-text` embeddings model used when building that index.

Manual recovery sequence, only if the helper script is unavailable:

```powershell
docker compose --profile local-embeddings up -d ollama qdrant
docker compose exec ollama ollama pull nomic-embed-text
docker compose --profile tools run --rm vector-index
```

Expected result: the index command reports chunks indexed for each available bank/year. If it reports that no matching report is available, inspect the local corpus before trying again. If it reports unavailable embeddings, first confirm the model with `docker compose exec ollama ollama list`.

## 7. Market Watch collector

The collector is a separate background service. It reads the official public Market Watch page every 30 minutes and stores immutable, dated snapshots locally.

```powershell
docker compose --profile market-collector up -d --build market-collector
docker compose logs --tail=30 market-collector
```

The collector writes snapshots under `data/market-snapshots/` and its run health under `data/market-collection-runs/`. A failed collection must not replace the most recent verified quote with an estimate. The Testing dashboard therefore labels stale market data as degraded.

## 8. Groq configuration

Store the key as one unquoted line in `.env`:

```env
GROQ_API_KEY=gsk_your_key_here
```

After changing it, recreate the services that receive environment variables:

```powershell
Remove-Item Env:GROQ_API_KEY -ErrorAction SilentlyContinue
docker compose up -d --force-recreate chat-api testing-api
```

The first command prevents an old PowerShell environment variable from overriding `.env`. It does not reveal the key. A `401 Invalid API Key` in the Testing Lab means the configured key is invalid or was not passed into the recreated container; it is not a Chat evidence failure.

## 9. Troubleshooting

### Port already in use

If Docker cannot bind `8000` or `8001`, another local process owns that port. Identify it before stopping anything:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  Select-Object LocalAddress, LocalPort, OwningProcess

Get-Process -Id <OwningProcess> |
  Select-Object Id, ProcessName, Path
```

Repeat with port `8001` if needed. Stop the conflicting application only when you have confirmed that it is safe to stop.

### The Chat waits too long

The Chat may wait when a request requires an optional semantic decision or external provider. A structurally incomplete report-access question now receives a direct metric clarification instead of invoking unnecessary Groq routing. Check `chat-api` logs if a normal validated-metric question remains slow.

### A campaign shows an execution issue

Open the Executor stage. It retains API status, latency, response type and transport errors per scenario. A partial campaign is shown as **Completed with execution issue** when some responses completed and another transport request failed. This is different from a failed financial assertion.

### Qdrant is not ready

The Chat remains usable: numeric facts and lexical documentary search continue. Pull the model, then run the one-shot vector-index job when convenient. Do not rebuild vectors merely because one query did not find a sufficiently relevant passage.

## 10. Local artefacts and safe cleanup

| Artefact | Location | Safe to remove? |
| --- | --- | --- |
| Campaign history and reports | `data/autotest/` | Yes, through the Testing dashboard when no history is needed |
| Playwright output | `chat/web/test-results/` | Yes; generated test evidence only |
| Qdrant vectors | Docker volume `qdrant_data` | Rebuildable from the approved corpus, but remove only intentionally |
| Ollama model | Docker volume `ollama_data` | Re-downloadable, but first startup will be slower |
| Official PDFs and validated facts | `data/raw/`, `data/normalized/` | No, unless a source-data change is reviewed and validated |

For code-level extension rules, go to the [Developer guide](developer-guide.md). For publication outside the workstation, go to [Security and deployment](security-and-deployment.md).
