# Sécurité et déploiement — MyFinance

## Position actuelle

MyFinance est livré comme application **locale**. Docker lie par défaut le Chat,
Testing, Qdrant et Ollama à `127.0.0.1`. Ils sont donc accessibles depuis le
poste de développement, pas depuis le réseau local ou Internet.

Cette décision protège particulièrement :

- la plateforme Testing, qui peut lancer des campagnes et supprimer leurs
  rapports locaux ;
- Qdrant et Ollama, qui sont des services internes et n’ont pas à être exposés ;
- les diagnostics techniques de l’API.

## Protections applicatives

Les deux APIs installent :

- CORS restreint aux origines locales en mode `local` ;
- headers `no-store`, `nosniff`, `DENY` pour les frames et `no-referrer` ;
- une limite de débit par processus quand elle est activée ;
- une configuration `production` qui échoue au démarrage si les origines CORS
  ou les noms d’hôtes acceptés sont absents ou utilisent `*` ;
- la désactivation du diagnostic de plan détaillé dans l’API Chat publique.

Les paramètres sont dans `.env`, jamais dans Git :

```env
MYFINANCE_DEPLOYMENT_MODE=local
MYFINANCE_CORS_ORIGINS=
MYFINANCE_ALLOWED_HOSTS=
MYFINANCE_RATE_LIMIT_PER_MINUTE=0
```

En mode `production`, fournissez des valeurs explicites, y compris une limite
strictement positive ; une valeur à `0` arrête volontairement le service :

```env
MYFINANCE_DEPLOYMENT_MODE=production
MYFINANCE_CORS_ORIGINS=https://app.example.com
MYFINANCE_ALLOWED_HOSTS=api.example.com
MYFINANCE_RATE_LIMIT_PER_MINUTE=60
```

Ne mettez jamais de clé Groq dans le code, les captures, les rapports de
campagne ou un message de discussion. Gardez-la uniquement dans `.env`, le
gestionnaire de secrets de l’hébergeur ou l’environnement du conteneur.

## Ce qu’il faut avant une publication Internet

Le mode `production` est un garde-fou de configuration, pas un système complet
d’authentification. Avant exposition publique, il faut impérativement :

1. un reverse proxy avec TLS/HTTPS ;
2. une authentification et une autorisation métier ou SSO devant Testing ;
3. une limite de débit partagée au proxy (pas seulement en mémoire dans une API) ;
4. des logs centralisés, alertes de santé et sauvegardes de données ;
5. des secrets stockés dans un coffre, avec rotation ;
6. aucun port Qdrant, Ollama ou Testing API publié directement ;
7. une revue des politiques de conservation de documents et traces.

Une architecture sûre est :

```text
Internet
  → reverse proxy TLS + authentification + rate limit partagé
  → Chat Web / Chat API
      ├─ Qdrant privé sur le réseau Docker
      └─ Ollama privé sur le réseau Docker

Testing API et Testing Web : réseau d’administration seulement
```

## Exploitation locale

```powershell
.\scripts\myfinance.ps1 start
.\scripts\myfinance.ps1 status
.\scripts\myfinance.ps1 stop
```

Après un changement de code dans l’API Chat, reconstruisez uniquement ce
service :

```powershell
docker compose up -d --build chat-api
```

`testing-api` monte son code source localement et se met à jour avec :

```powershell
docker compose up -d --force-recreate testing-api
```

Le réindexage Qdrant est réservé à un changement de corpus ou de faits ; voir
[data-coverage.md](data-coverage.md).
