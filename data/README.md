# Données MyFinance

Ce dossier sépare toujours le document officiel, le texte extrait et les chiffres
financiers. Un chiffre n'est jamais une source : le PDF officiel reste la preuve.

```text
data/
├── raw/official-reports/etat financier/<banque>/<rapport>.pdf
├── reference/financial_metrics.json
├── normalized/
│   ├── corpus/<banque>/<année>/
│   │   ├── documents.json
│   │   └── evidence_chunks.jsonl
│   └── facts/
│       └── auto_validated/<banque>/<année>/financial_facts.json
├── validation-runs/<banque>/<année>/
│   ├── report.json
│   └── rejected_facts.json
```

## `raw/`

Les PDF officiels téléchargés auprès des banques ou de leurs publications
réglementaires. Ils ne sont jamais modifiés par le programme.

## `reference/`

Les définitions métier versionnées et indépendantes des chiffres extraits. Le
catalogue `financial_metrics.json` indique le sens d'une métrique, ses synonymes,
le tableau où elle doit être trouvée et les contrôles exigés avant validation.

## `normalized/corpus/`

Une transcription de travail d'un seul PDF. Chaque dossier représente exactement
une banque et une année.

- `documents.json` décrit le PDF : identifiant, hash SHA-256 et nombre de pages.
- `evidence_chunks.jsonl` contient des extraits de texte qui ne traversent jamais
  une page. Chaque extrait garde la banque, l'année, la page et le hash du PDF.

Ce corpus permet de retrouver un passage, mais il ne constitue pas une vérité
financière à lui seul.

## `normalized/facts/auto_validated/`

Chiffres ayant passé les contrôles déterministes : provenance du PDF, hash,
page, extrait source, unité, périmètre, unicité et contrôles comptables
applicables. C'est le seul emplacement dont l'API peut utiliser les valeurs.

## `validation-runs/`

Rapport du validateur automatique. Les faits rejetés y restent avec leurs
contrôles et leurs motifs ; ils ne sont jamais retournés à un utilisateur.

## Règle de lecture

Pour toute réponse : **fait auto-validé → extrait de preuve → PDF officiel**.
Si l'un de ces éléments manque, le système clarifie la demande ou ne conclut pas.
