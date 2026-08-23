[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "status", "reindex", "stop")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Compose {
    param([string[]]$Arguments)

    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose a échoué (code $LASTEXITCODE)."
    }
}

function Wait-ForOllama {
    Write-Host "Vérification d’Ollama..."
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        & docker compose exec -T ollama ollama list *> $null
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Ollama ne répond pas après une minute. Vérifie Docker Desktop puis relance la commande."
}

function Test-VectorIndexExists {
    try {
        $collection = Invoke-RestMethod -Uri "http://127.0.0.1:6333/collections/myfinance_evidence" -TimeoutSec 5
        return [Int64]$collection.result.points_count -gt 0
    }
    catch {
        return $false
    }
}

function Start-MyFinance {
    Write-Host "[1/5] Construction et démarrage des services MyFinance..."
    Invoke-Compose @("--profile", "local-embeddings", "up", "-d", "--build")

    Wait-ForOllama

    Write-Host "[2/5] Vérification du modèle d’embeddings..."
    Invoke-Compose @("exec", "-T", "ollama", "ollama", "pull", "nomic-embed-text")

    if (Test-VectorIndexExists) {
        Write-Host "[3/5] Index RAG Qdrant déjà présent : aucune réindexation nécessaire."
    }
    else {
        Write-Host "[3/5] Construction de l’index RAG Qdrant... Cette étape peut prendre quelques minutes."
        Invoke-Compose @("--profile", "tools", "build", "vector-index")
        Invoke-Compose @("--profile", "tools", "run", "--rm", "vector-index")
    }

    Write-Host "[4/5] Application de l’index au chat..."
    Invoke-Compose @("up", "-d", "--build", "chat-api")

    Write-Host "[5/5] Démarrage de la collecte Market Watch toutes les 30 minutes..."
    Invoke-Compose @("--profile", "market-collector", "up", "-d", "--build", "market-collector")
    Show-MyFinanceStatus
}

function Reindex-MyFinance {
    Invoke-Compose @("--profile", "local-embeddings", "up", "-d", "ollama", "qdrant")
    Wait-ForOllama
    Invoke-Compose @("exec", "-T", "ollama", "ollama", "pull", "nomic-embed-text")
    Invoke-Compose @("--profile", "tools", "build", "vector-index")
    Invoke-Compose @("--profile", "tools", "run", "--rm", "vector-index")
    Invoke-Compose @("up", "-d", "--build", "chat-api")
    Show-MyFinanceStatus
}

function Show-MyFinanceStatus {
    Write-Host ""
    Write-Host "État des services :"
    Invoke-Compose @("ps")
    Write-Host ""
    Write-Host "Derniers événements Market Watch :"
    & docker compose logs --tail=5 market-collector
}

Set-Location $ProjectRoot
& docker version --format '{{.Server.Version}}' *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop n’est pas accessible. Ouvre Docker Desktop, puis relance cette commande."
}

switch ($Action) {
    "start" { Start-MyFinance }
    "status" { Show-MyFinanceStatus }
    "reindex" { Reindex-MyFinance }
    "stop" { Invoke-Compose @("--profile", "local-embeddings", "--profile", "market-collector", "stop") }
}
