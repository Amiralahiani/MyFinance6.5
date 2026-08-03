# Démonstration MyFinance

## Préparation

Dans quatre terminaux depuis la racine du dépôt :

```powershell
# 1. API du Chat
uv run python chat/scripts/run_orchestrator.py

# 2. Interface du Chat
cd chat/web
npm install
npm run dev:chat

# 3. API et interface Testing
$env:GROQ_API_KEY = "votre-cle"
uv run python autotest/scripts/run_testing_api.py
```

Dans un quatrième terminal :

```powershell
cd autotest/web
npm install
npm run dev:testing
```

Ouvrez le Chat sur `http://127.0.0.1:3000` et Testing sur `http://127.0.0.1:3001`.

## Déroulé conseillé

1. Dans le Chat, posez une question avec banque, exercice et métrique ; vérifiez la valeur et sa source.
2. Posez une question sans année ou sans preuve suffisante ; montrez la demande de précision ou le refus de conclure.
3. Dans Testing, lancez une campagne API et observez les étapes et les rapports de synthèse et d’audit.
4. Lancez le contrôle visuel Playwright depuis Testing pour montrer le parcours réel de l’interface Chat.

## Après la démonstration

Les données générées par Testing sont locales dans `data/autotest/`. Elles sont exclues de Git. Pour repartir d’un état vide, arrêtez le service Testing puis supprimez ce dossier.
