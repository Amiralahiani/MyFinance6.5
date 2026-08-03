# États des faits financiers

Un fait suit ce cycle :

```text
PDF officiel → extraction en mémoire → validation déterministe → auto_validated | rejected
```

- `auto_validated/` : seules valeurs utilisables dans une réponse financière.
- `validation-runs/<banque>/<année>/rejected_facts.json` : candidats refusés avec
  les motifs de chaque contrôle.
