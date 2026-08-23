# Guide développeur — MyFinance

Ce guide décrit le code actif, ses frontières et la manière de le faire évoluer
sans casser la règle centrale du projet : un chiffre présenté comme financier
doit être traçable jusqu’à un PDF officiel, une page et un extrait.

## 1. Carte du dépôt

```text
shared/contracts/       modèles Pydantic et protections runtime partagées
chat/
  api/                  API FastAPI et orchestration de conversation
  knowledge/            PDF, corpus, extraction, validation et Qdrant
  market/               cotations officielles, snapshots et fraîcheur
  web/                  interface React et tests Playwright du Chat
autotest/
  api/                  API de campagnes, SSE et persistance SQLite locale
  src/                  générateur, planner, exécuteurs, évaluateur, critic
  web/                  tableau de bord React de validation
data/                   preuves, corpus, faits validés et références métier
docker/                 images applicatives et navigateur Playwright visible
scripts/                commande PowerShell de démarrage et maintenance
```

`shared/contracts` ne contient pas de logique métier bancaire. Il définit les
formes échangées entre composants, notamment `ConversationRequest`,
`ConversationContext`, `FinancialFact`, `EvidenceChunk` et les protections de
configuration runtime. Cette séparation évite que l’interface, l’API Chat et la
plateforme de tests aient des interprétations différentes d’une réponse.

## 2. Parcours d’une question Chat

```text
React Chat
  → POST /api/conversation/answer
  → normalise_financial_request()
  → assess_request()
  → garde-fous déterministes et plan de tour
  → fait validé / recherche documentaire / marché / clarification
  → réponse typée avec contexte et preuves
```

Les points d’entrée importants sont :

| Fichier | Rôle |
| --- | --- |
| `chat/api/.../main.py` | Routes HTTP, CORS, headers de sécurité, limite de débit et exposition contrôlée des PDF. |
| `chat/api/.../language.py` | Réparation non ambiguë de la formulation utilisateur ; elle ne choisit jamais une source. |
| `chat/api/.../assessment.py` | Détection de banque, année, métrique et décision répondre / clarifier / s’abstenir. |
| `chat/api/.../dialogue.py` | Machine de conversation, comparaisons, continuité documentaire et garde-fous. |
| `chat/api/.../evidence_synthesis.py` | Synthèse limitée aux extraits déjà sélectionnés. |
| `chat/knowledge/.../facts.py` | Lecture des faits `auto_validated` et extraction strictement sourcée hors noyau. |
| `chat/knowledge/.../corpus.py` | Recherche lexicale et hybride ; filtre toujours banque, année, page et provenance. |
| `chat/knowledge/.../vector_store.py` | Couche Qdrant optionnelle. Son indisponibilité remet la recherche lexicale en service. |
| `chat/market/.../collector.py` | Lecture officielle, snapshots immuables et rapport de dernière collecte. |

### Types de réponse

- `numeric` : fait automatiquement validé. La réponse doit inclure valeur,
  unité, exercice, PDF, page et extrait.
- `comparison` : plusieurs faits automatiquement validés, comparables dans le
  même exercice et la même unité.
- `documentary` : explication à partir d’extraits de PDF, sans transformer un
  extrait narratif en chiffre.
- `market` : donnée de marché officielle datée ; si la lecture échoue, une
  indisponibilité explicite est retournée.
- `clarification` : information ou preuve insuffisante. C’est une réponse
  correcte, pas une erreur à masquer.

## 3. Règles de sûreté du Chat

Les garde-fous sont écrits dans `dialogue.py` et vérifiés par
`chat/tests/channels/api/` :

1. pas de valeur sans fait `auto_validated` ;
2. pas de conversion de devise sans taux officiel daté ;
3. pas d’accès supposé à un compte bancaire personnel ;
4. pas de classement « safest » sans critère mesurable et sourçable ;
5. pas de réponse pour un exercice hors corpus ;
6. une comparaison complète ne demande pas de précision déjà fournie ;
7. le modèle externe ne peut ni sélectionner une source ni remplacer un
   contrôle déterministe.

Groq est donc une couche rédactionnelle ou exploratoire. Il n’est jamais la
preuve d’une valeur financière.

## 4. De PDF à fait affichable

```text
PDF officiel immuable
  → ingestion page par page et SHA-256
  → chunks avec banque, année, page, section et source
  → candidat de métrique
  → contrôles d’unicité, unité, périmètre et bilan
  → financial_facts.json avec validation_status=auto_validated
  → API Chat
```

Les définitions métier sont dans `data/reference/financial_metrics.json`. Elles
décrivent synonymes, libellés acceptés, section de l’état financier et règles de
validation ; elles ne doivent jamais contenir de valeur annuelle.

Pour comprendre le format des preuves, consultez aussi
[data-model.md](data-model.md) et [data-coverage.md](data-coverage.md).

## 5. RAG et Qdrant

Qdrant indexe les mêmes chunks déjà présents dans le corpus. Il améliore la
proximité sémantique d’une demande documentaire, mais ne remplace ni le filtre
exact banque/année ni le PDF. La hiérarchie de décision est :

```text
fait validé pour les chiffres
  > extrait PDF filtré pour les explications
  > Qdrant pour enrichir le rappel d’extraits
  > recherche lexicale si Qdrant ou Ollama est absent
```

Après un ajout ou une modification de PDF/corpus, reconstruire l’index :

```powershell
.\scripts\myfinance.ps1 reindex
```

Ne relancez pas cette commande pour une modification d’interface ou de texte de
réponse : elle est réservée aux preuves documentaires.

## 6. Plateforme Agentic Testing

```text
Catalogue déterministe ou charters d’exploration
  → Planner
  → Executor API et, si demandé, Web
  → Evaluator déterministe
  → AI Critic Groq optionnel
  → rapports JSON, Markdown et HTML
```

| Partie | Responsabilité |
| --- | --- |
| `autotest/api/.../main.py` | Campagnes, événements SSE, arrêt/reprise/suppression, état de la stack. |
| `autotest/src/.../scenarios/` | Catalogue reproductible et charters d’exploration. |
| `autotest/src/.../validators/` | Contrats déterministes : valeur, année, unité, source, comportement. |
| `autotest/src/.../executors/` | Appels au vrai Chat API et à l’interface Web. |
| `autotest/src/.../agents/` | Génération/critique Groq bornées par les preuves et le verdict déterministe. |
| `autotest/web/` | Affichage des stages, historique, preuves et navigateur Playwright. |

Un échec Groq ne transforme pas automatiquement un test en échec métier. Le
tableau de bord indique que les scores IA sont indisponibles et conserve le
verdict déterministe, les règles et les sources.

## 7. Ajouter une évolution correctement

1. Écrire l’intention métier et le comportement attendu.
2. Identifier la frontière : contrat partagé, données, API, Chat, interface ou
   campagne de test.
3. Modifier la logique minimale et ajouter le test de régression dans le même
   changement.
4. Si un fait financier est concerné, ne l’ajouter qu’après validation PDF ; ne
   jamais le saisir dans une réponse ou un prompt.
5. Exécuter :

```powershell
uv run ruff check .
uv run pytest -q
cd chat/web; npm run build
cd ..\..\autotest\web; npm run build
```

6. Relancer une campagne ciblée et un parcours Playwright lorsque le changement
   est visible par l’utilisateur.
7. Mettre à jour la documentation de la frontière modifiée.

## 8. Démarrage et diagnostics

Pour une stack locale complète :

```powershell
.\scripts\myfinance.ps1 start
.\scripts\myfinance.ps1 status
```

Les deux interfaces sont sur `http://127.0.0.1:3000` et
`http://127.0.0.1:3001`. Les APIs et outils internes sont liés à `127.0.0.1`
par défaut ; ils ne sont pas conçus pour être publiés directement.

Pour les responsabilités de sécurité et de déploiement, lire
[security-and-deployment.md](security-and-deployment.md).
