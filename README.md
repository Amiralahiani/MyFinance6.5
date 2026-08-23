# MyFinance

> Assistant d’analyse d’états financiers bancaires, fondé sur des preuves officielles et vérifié par une plateforme de tests autonome.

MyFinance ne répond pas à partir d’estimations. Chaque réponse chiffrée est construite à partir d’un fait financier validé, relié à un extrait et au PDF officiel d’origine. Lorsqu’une information est ambiguë ou absente, l’application clarifie ou refuse de conclure.

## Ce que le projet démontre

| Besoin | Réponse MyFinance |
| --- | --- |
| Retrouver un indicateur bancaire | Valeur validée avec banque, exercice, unité et preuve PDF |
| Comprendre un passage du rapport | Analyse documentaire avec extraits sourcés et pages associées |
| Éviter une réponse fragile | Clarification ou non-conclusion, jamais de chiffre inventé |
| Vérifier le produit | Campagnes API, rapports d’audit et parcours Playwright visibles |

Le périmètre actuel couvre les états financiers individuels 2021–2025 d’Amen Bank, Attijari Bank, BIAT, Banque de Tunisie et Banque Zitouna.

## Architecture

```text
Utilisateur
  → Chat React → API Chat FastAPI
                    ├─ Faits auto-validés → PDF officiels
                    └─ Corpus PDF sourcé → PDF officiels

Testing React → API Testing
                  ├─ API Chat
                  ├─ Groq : génération et évaluation
                  └─ Rapports et contrôles Playwright
```

La frontière est volontairement nette : `chat/` sert l’utilisateur, `autotest/` le vérifie, `shared/` porte les contrats et `data/` conserve les preuves.

## Démarrage local

Prérequis : Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 20+ et, pour les campagnes qualitatives, une clé Groq.

```powershell
uv sync --all-groups
```

Lancez ensuite les services dans des terminaux séparés :

```powershell
# 1 — API du Chat : http://127.0.0.1:8000
uv run python chat/scripts/run_orchestrator.py

# 2 — Interface du Chat : http://127.0.0.1:3000
cd chat/web
npm install
npm run dev:chat

# 3 — API Testing : http://127.0.0.1:8001
$env:GROQ_API_KEY = "votre-cle"
uv run python autotest/scripts/run_testing_api.py

# 4 — Interface Testing : http://127.0.0.1:3001
cd autotest/web
npm install
npm run dev:testing
```

Commencez la démo dans le Chat, puis ouvrez Testing pour lancer une campagne et consulter sa synthèse ou son audit détaillé. Le déroulé complet est dans le [guide de démonstration](docs/demo.md).

## Qualité et vérification

```powershell
uv run ruff check .
uv run pytest -q

cd chat/web
npm run test:e2e
```

Les résultats Playwright, campagnes, captures et bases SQLite sont des traces locales : ils sont volontairement exclus de Git.

La vérification est aussi exécutée automatiquement par GitHub Actions à chaque
pull request et sur `main` : Ruff, tests Python et builds des deux interfaces.

## Démarrage Docker simplifié

Depuis PowerShell à la racine du projet, une seule commande démarre les services,
télécharge le modèle d'embeddings si nécessaire, indexe les rapports dans Qdrant et
active la collecte Market Watch :

```powershell
.\scripts\myfinance.ps1 start
```

Les commandes courantes sont ensuite :

```powershell
.\scripts\myfinance.ps1 status   # état des conteneurs et dernière collecte
.\scripts\myfinance.ps1 reindex  # après ajout ou modification de rapports
.\scripts\myfinance.ps1 stop     # arrêt propre des services
```

Le script ne modifie pas `.env` et ne demande jamais la clé Groq dans le terminal.
Lors des démarrages suivants, il détecte l'index Qdrant existant et ne recalcule
pas les vecteurs. Utilisez seulement `reindex` après l'ajout ou la modification
de rapports.

## RAG hybride avec Qdrant (avancé)

La recherche lexicale sourcée reste la référence de MyFinance. Qdrant l'enrichit avec une
recherche sémantique sur les mêmes chunks et ne remplace jamais les contrôles de banque,
année, page et extrait PDF.

```powershell
# Démarre Qdrant et l'API, puis l'embeddings local Ollama.
# Avant le premier démarrage, créez `.env` depuis `.env.example` et renseignez
# uniquement `GROQ_API_KEY` : Groq rédige la réponse finale, Ollama sert aux embeddings.
docker compose --profile local-embeddings up -d
docker compose exec ollama ollama pull nomic-embed-text

# Construit les vecteurs à partir du corpus déjà extrait et validé.
docker compose --profile tools run --rm vector-index
```

Dans Docker, l'indexeur utilise automatiquement l'adresse interne d'Ollama.
La valeur `MYFINANCE_EMBEDDINGS_URL=http://127.0.0.1:11434/...` reste réservée
aux lancements Python directement depuis Windows.

Les interfaces sont ensuite disponibles sur les ports 3000 (Chat) et 3001 (Testing).
Sans Qdrant, sans Ollama ou sans index construit, MyFinance revient automatiquement à la
recherche lexicale locale : aucune réponse n'est bloquée ni remplacée par une réponse non sourcée.

L'image de l'API inclut aussi Chromium pour lire la cotation publique officielle de la Bourse de Tunis.
La première construction Docker est donc plus longue ; sans ce navigateur, l'agent Market Watch refuse
volontairement d'afficher un cours non vérifié.

## Collecte Market Watch toutes les 30 minutes

Le chat peut lire le cours public courant sans écrire de donnée. Pour conserver aussi un historique
daté et vérifiable, démarrez le collecteur séparé ci-dessous. Il crée un instantané immuable à chaque
passage et enregistre explicitement chaque succès ou échec ; il ne fabrique jamais de cours.

```powershell
docker compose --profile market-collector up -d market-collector
docker compose logs -f market-collector
```

Les données restent dans `data/market-snapshots/` et l'état du dernier passage dans
`data/market-collection-runs/latest.json`. Pour l'arrêter :

```powershell
docker compose --profile market-collector stop market-collector
```

## Documentation technique et sécurité

- [Guide développeur](docs/developer-guide.md) : flux de code, responsabilités
  des modules, contrats, tests et procédure d’évolution.
- [Couverture des données](docs/data-coverage.md) : matrice des faits validés et
  procédure d’ajout de PDF, métriques et vecteurs.
- [Sécurité et déploiement](docs/security-and-deployment.md) : ports locaux,
  protections runtime et prérequis avant exposition publique.

Les ports Docker sont liés à `127.0.0.1` par défaut. MyFinance est donc sûr pour
le développement local ; une publication Internet requiert un reverse proxy TLS,
une authentification et une limite de débit partagée.

## Organisation du dépôt

| Dossier | Responsabilité |
| --- | --- |
| [chat/](chat/README.md) | API de conversation, interface utilisateur, corpus et tests E2E |
| [autotest/](autotest/README.md) | Campagnes Agentic Testing, Groq, rapports et interface de suivi |
| [shared/](shared/) | Contrats Python échangés entre les applications |
| [data/](data/README.md) | PDF officiels, corpus, références métier et faits validés |
| [docs/](docs/README.md) | Architecture, modèle de données, décisions et démo |

## Documentation et contribution

- [Architecture](docs/architecture.md)
- [Modèle de données](docs/data-model.md)
- [Guide de démonstration](docs/demo.md)
- [Cycle agile et règles de contribution](CONTRIBUTING.md)

Les documents financiers et le corpus sont des éléments de preuve. Ne supprimez pas de données dans `data/` sans validation métier explicite.
