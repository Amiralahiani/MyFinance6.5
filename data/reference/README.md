# Référentiel métier

`financial_metrics.json` est la source unique des définitions d'indicateurs. Son
profil d'extraction commun couvre sept métriques comparables dans les états
financiers individuels 2021–2025 d'Amen Bank, Attijari Bank, BIAT, Banque de
Tunisie et Banque Zitouna. Il ne contient aucun montant financier.

Le catalogue v3.0 définit les sept métriques du profil commun qui sont extraites
et validées automatiquement pour les cinq banques.

La couverture mesurée est de 174 faits auto-validés sur 175 emplacements
attendus. Le seul emplacement absent est le résultat net Banque Zitouna 2021 :
le calque texte de ce PDF fusionne les deux colonnes en une suite de chiffres
isolés, donc le premier montant annuel ne peut pas être choisi sans ambiguïté.
Le validateur le laisse volontairement absent ; il ne crée pas de valeur estimée.

Une métrique ayant `user_intent_status: supported` peut être comprise dans une
question. Aucune valeur ne peut être renvoyée avant la création puis la validation
d'un fait dans `normalized/facts/auto_validated/`.

Une métrique absente ou ambiguë reste hors des réponses jusqu’à ce qu’une preuve
PDF non ambiguë permette son extraction.
