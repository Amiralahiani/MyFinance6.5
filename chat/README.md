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

Pour le modèle de données et la chaîne de preuve, consultez [../docs/architecture.md](../docs/architecture.md) et [../data/README.md](../data/README.md).
