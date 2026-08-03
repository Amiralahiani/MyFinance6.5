# Agentic Testing

La plateforme Testing vérifie le Chat à travers de vraies requêtes API et des parcours Playwright. Elle sépare la génération de scénarios, l’autorisation des actions, l’exécution, l’évaluation et le reporting.

## Cycle d’une campagne

```text
Generator → Planner → Executor → Evaluator → Critic
                                            ├─ sans contre-vérification → Reporter
                                            └─ contre-vérification requise
                                               → Planner complémentaire
                                               → Executor complémentaire
                                               → Evaluator complémentaire
                                               → Reporter
```

Le Critic ne déclenche les étapes complémentaires que lorsqu’une incertitude justifie réellement une contre-vérification.

## Contenu

```text
api/      API FastAPI, persistance SQLite locale et flux SSE de suivi
src/      Moteur de campagnes, garde-fous, évaluation, critic et reporting
web/      Interface React de suivi, lancement et consultation des rapports
configs/  Limites de campagne et modèles Groq
scripts/  Points d’entrée CLI reproductibles
tests/    Tests unitaires et d’intégration
```

## Lancer la plateforme

L’API du Chat doit être disponible sur `http://127.0.0.1:8000`. La clé Groq reste dans le terminal ou dans `.env` local : elle ne doit jamais être versionnée.

```powershell
# API Testing : http://127.0.0.1:8001
$env:GROQ_API_KEY = "votre-cle"
uv run python autotest/scripts/run_testing_api.py

# Interface Testing : http://127.0.0.1:3001
cd autotest/web
npm install
npm run dev:testing
```

## Résultats

Une campagne produit une synthèse lisible, un audit détaillé, les versions Markdown et le JSON brut. Les fichiers sont conservés localement dans `data/autotest/`, exclus de Git et supprimables sans effet sur le code ni les données financières.

## Vérification

```powershell
uv run pytest autotest/tests -q
```

Le contrôle visuel Playwright reste séparé d’une campagne Groq : il teste l’interface Chat, pas la qualité d’un scénario financier.
