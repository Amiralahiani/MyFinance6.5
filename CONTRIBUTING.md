# Contribution et cycle de livraison

## Architecture

MyFinance est organisé par responsabilité : `chat/` sert l’utilisateur, `autotest/` vérifie le comportement, `shared/` porte les contrats et `data/` conserve les preuves et faits validés. Une application ne dépend pas de l’interface de l’autre ; elles communiquent uniquement par les API locales et les contrats partagés.

## Cycle agile d’une évolution

1. Formuler une intention de risque ou un besoin utilisateur et définir son critère d’acceptation.
2. Modifier le plus petit périmètre concerné : contrat, logique, interface ou scénario de test.
3. Ajouter ou adapter le test déterministe correspondant.
4. Exécuter `uv run ruff check .`, `uv run pytest -q`, puis compiler l’interface touchée.
5. Vérifier le parcours réel dans Testing si l’évolution concerne le Chat, Groq ou le reporting.
6. Documenter une décision structurante dans `docs/decision-log.md`.

## Règles de qualité

- Aucun chiffre n’est ajouté sans fait `auto_validated` et preuve PDF.
- Aucune clé ou trace d’exécution ne va dans Git ; `.env`, `data/autotest/` et les résultats Playwright sont ignorés.
- Les scripts de `chat/scripts/` et `autotest/scripts/` restent des outils explicites et reproductibles, jamais des tâches lancées au démarrage d’une API.
- Toute suppression de données de `data/` doit être explicitement validée : les PDF et corpus font partie de la preuve métier.
