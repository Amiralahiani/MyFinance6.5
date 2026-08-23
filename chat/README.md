# Chat MyFinance

Le Chat est l’application utilisateur. Il répond aux questions financières à partir de faits auto-validés et explique les rapports à partir d’extraits PDF sourcés.

## Responsabilités

```text
api/        API FastAPI : routage, sûreté, conversation et exposition des documents
knowledge/  Catalogue, ingestion PDF, corpus, extraction et validation déterministe
market/     Logique et données de marché associées
web/        Interface React/Vite et parcours Playwright
scripts/    Commandes explicites de lancement et de reconstruction des données
tests/      Tests métier, API et intégration
```

## Contrat de réponse

| Situation | Comportement attendu |
| --- | --- |
| Valeur validée | Afficher valeur, banque, exercice, unité et source |
| Demande ambiguë | Poser la précision minimale utile |
| Preuve absente ou insuffisante | Ne pas conclure et expliquer pourquoi |
| Question documentaire | Répondre avec des extraits et leurs pages |

## Lancer le Chat

Depuis la racine du dépôt :

```powershell
# API : http://127.0.0.1:8000
uv run python chat/scripts/run_orchestrator.py

# Interface : http://127.0.0.1:3000
cd chat/web
npm install
npm run dev:chat
```

## Vérifier l’interface réelle

```powershell
cd chat/web
npm run test:e2e
```

Le test démarre le vrai parcours Chat local. Ses résultats sont générés dans l’environnement de travail et ne doivent pas être versionnés.

## Synthèse Groq sourcée (optionnelle)

La synthèse rédactionnelle reste optionnelle. Même lorsqu’elle est activée, Groq
ne reçoit que les extraits PDF déjà sélectionnés : il ne choisit pas les sources,
ne produit pas de chiffres et son texte est rejeté s’il ne fournit pas une citation
exacte présente sur la page indiquée. En cas d’indisponibilité ou de validation
échouée, MyFinance affiche l’extrait source plutôt qu’une réponse non vérifiable.

```powershell
$env:GROQ_API_KEY = "votre-cle"
$env:MYFINANCE_USE_LLM = "true"
$env:MYFINANCE_LLM_PROVIDER = "groq"
# Facultatif : le modèle par défaut est celui du rôle generator dans autotest.
$env:MYFINANCE_GROQ_MODEL = "openai/gpt-oss-20b"
# Réécrit la demande entière (orthographe, grammaire, espaces) avant la recherche.
# Cette étape ne répond jamais à la question et ne choisit aucune source.
$env:MYFINANCE_QUERY_REWRITE = "true"
uv run python chat/scripts/run_orchestrator.py
```

La réécriture de demande est activée automatiquement lorsqu'une clé Groq est
présente. Sans clé, MyFinance applique uniquement les réparations déterministes
non ambiguës (espaces oubliés, noms de banques collés et vocabulaire financier).

Pour le modèle de données et la chaîne de preuve, consultez [../docs/architecture.md](../docs/architecture.md), [../docs/developer-guide.md](../docs/developer-guide.md), [../docs/data-coverage.md](../docs/data-coverage.md) et [../data/README.md](../data/README.md).
