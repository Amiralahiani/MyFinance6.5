# Couverture et extension des données — MyFinance

## Périmètre mesuré

Le noyau actuel contient les rapports individuels 2021–2025 de cinq banques et
sept métriques comparables. La commande suivante établit la couverture réelle à
partir des fichiers `financial_facts.json`, sans modifier aucune donnée :

```powershell
uv run python chat/scripts/audit_fact_coverage.py
```

À l’état actuel, elle indique **25 rapports**, **175 cellules attendues** et
**175 faits auto-validés (100 %)**. Le `net_income` Banque Zitouna 2021 est
extrait de la ligne propre du bilan (« Résultat de l’exercice 60 117 51 411 »,
page PDF 2) : le compte de résultat de la page 4 confirme le même montant mais
son OCR espace chaque chiffre.

Pour faire de la complétude une règle de livraison une fois le périmètre validé :

```powershell
uv run python chat/scripts/audit_fact_coverage.py --strict
```

La commande retourne alors un code non nul si une cellule cible est manquante.

## Procédure pour ajouter une donnée

1. Ajouter un PDF officiel dans `data/raw/official-reports/etat financier/<bank>/`.
2. Vérifier que le nom permet d’identifier sans ambiguïté banque et exercice.
3. Ajouter ou confirmer la définition de métrique dans
   `data/reference/financial_metrics.json` : libellés acceptés, section, unité,
   périmètre et règles. Ne jamais y placer une valeur annuelle.
4. Générer le corpus page par page et conserver le SHA-256 du PDF.
5. Exécuter les contrôles d’extraction et de validation. Une ambiguïté, une
   unité absente ou une rupture du bilan doit produire un rejet, pas un fait.
6. Vérifier le fait avec son PDF, sa page et son extrait avant de le laisser en
   `validation_status=auto_validated`.
7. Ajouter un test de valeur, de comparaison ou de comportement correspondant.
8. Réindexer Qdrant seulement après la mise à jour du corpus :

```powershell
.\scripts\myfinance.ps1 reindex
```

## Niveaux de confiance

| Niveau | Utilisation Chat |
| --- | --- |
| PDF officiel | preuve primaire, consultable. |
| Chunk de corpus | preuve pour une explication documentaire, avec page. |
| `candidate` | jamais affiché comme chiffre à l’utilisateur. |
| `auto_validated` | seul niveau autorisé pour une réponse chiffrée. |
| Snapshot de marché officiel | cours daté, séparé des états financiers. |

Qdrant ne change aucun de ces niveaux. Il stocke des vecteurs de chunks afin
d’améliorer le rappel documentaire ; l’API recoupe toujours le résultat avec la
provenance source.

## Couverture du marché

Les instruments actuellement vérifiés dans `data/reference/market_instruments.json`
sont Amen Bank, Attijari Bank, BIAT et Banque de Tunisie. Banque Zitouna est
explicitement marquée `not_mapped` : le Chat doit donc signaler l’indisponibilité
plutôt que d’associer un symbole supposé.

Le collecteur écrit des snapshots immuables toutes les 30 minutes. Sa fraîcheur
est lue par `GET /api/market/collection-health` et affichée dans Testing. Une
collecte échouée ne remplace jamais le dernier cours vérifié par une estimation.
