# Modèle de données

```text
PDF officiel
  → DocumentRecord
  → EvidenceChunk (corpus complet)
  → extraction en mémoire
  → FinancialFact auto_validated ou rejected
```

## `DocumentRecord`

Identité immuable d'un PDF : banque, exercice, chemin, hash SHA-256 et nombre de
pages.

## `EvidenceChunk`

Extrait textuel qui ne traverse jamais une page. Il conserve la banque, l'année,
la page, la section détectée, le chemin et le hash du PDF. Il sert aux réponses
explicatives et à la provenance, jamais comme preuve numérique suffisante à lui
seul.

## `FinancialFact`

Valeur financière normalisée avec libellé exact, valeur publiée, devise, unité,
périmètre, exercice, page et source. Après les contrôles déterministes, seuls
les faits `auto_validated` dans `facts/auto_validated/` peuvent servir à une
réponse chiffrée. Les rejets sont conservés dans `validation-runs/`.
