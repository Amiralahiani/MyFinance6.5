# Architecture produit — MyFinance 6.5

## Périmètre actif

Le projet couvre les états financiers **individuels** 2021–2025 d’Amen Bank,
Attijari Bank, BIAT, Banque de Tunisie et Banque Zitouna. Le noyau commun porte
sur sept métriques comparables, avec validation automatique avant publication.

## Les quatre réponses possibles

| Type de demande | Base utilisée | Exemple |
|---|---|---|
| Valeur publiée | Faits `auto_validated` | « Quel est le PNB BIAT en 2023 ? » |
| Explication documentaire | Corpus PDF sourcé | « Quelle est la politique de provisionnement ? » |
| Comparaison | Faits `auto_validated` sur plusieurs années + explication du corpus | « Comment les dépôts ont-ils évolué ? » |
| Calcul analytique | Faits `auto_validated` + formule versionnée | « Quel est le ROE moyen en 2024 ? » |

Une demande sans preuve suffisante reçoit une explication de l'absence de donnée ;
elle ne reçoit ni estimation ni chiffre inventé.

## Chaîne de production

```text
PDF officiel
  → corpus page par page
  → catalogue des métriques et questions
  → extraction en mémoire
  → validation déterministe
  → faits auto-validés / extraits narratifs sourcés
  → réponse utilisateur
```

## Architecture des données

```text
data/
├── raw/                         PDF officiels intouchables
├── reference/                   définitions métier et politique de réponse
├── normalized/
│   ├── corpus/<banque>/<année>/ texte page par page avec hash et provenance
│   └── facts/
│       └── auto_validated/      valeurs validées automatiquement, utilisables
├── validation-runs/             rapports de contrôles et rejets
```

## Règles non négociables

1. Le PDF est la preuve primaire.
2. Une valeur affichée au client provient exclusivement de `facts/auto_validated/`.
3. Une explication textuelle cite toujours un extrait du corpus et sa page.
4. Le catalogue décrit une métrique ; il ne contient jamais une valeur ou une page
   spécifique à une année.
5. Les pages, notes, unités et périmètres restent attachés aux faits ou extraits.
