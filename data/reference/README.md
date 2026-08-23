# Référentiel métier

`financial_metrics.json` est la source unique des définitions d'indicateurs. Son
profil d'extraction commun couvre sept métriques comparables dans les états
financiers individuels 2021–2025 d'Amen Bank, Attijari Bank, BIAT, Banque de
Tunisie et Banque Zitouna. Il ne contient aucun montant financier.

Le catalogue v3.0 définit les sept métriques du profil commun qui sont extraites
et validées automatiquement pour les cinq banques.

La couverture mesurée est de 175 faits auto-validés sur 175 emplacements
attendus. Le résultat net Banque Zitouna 2021 est validé depuis sa ligne nette
dans le bilan (page PDF 2), car le compte de résultat de la page 4 espace chaque
chiffre dans son calque texte tout en confirmant le même montant.

Une métrique ayant `user_intent_status: supported` peut être comprise dans une
question. Aucune valeur ne peut être renvoyée avant la création puis la validation
d'un fait dans `normalized/facts/auto_validated/`.

Une métrique absente ou ambiguë reste hors des réponses jusqu’à ce qu’une preuve
PDF non ambiguë permette son extraction.
