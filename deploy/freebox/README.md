# Déploiement sur la Freebox : site + API MCP du coach

Objectif : depuis **Claude mobile**, répondre aux questions du coach, modifier le plan, rapatrier les données et **voir le résultat
sur le site**, sans toucher au Mac. Les fichiers vivent sur la Freebox (dépôt git privé) ; le site les relit à chaque chargement
(rechargement automatique toutes les 30 s) : **aucune reconstruction, aucun export**.

```
 Claude mobile ──(connecteurs claude.ai)──►  Open Wearables  (existant, /mcp-wearables)   lecture des données
                                        ├─►  Nightscout      (existant)                    glycémie, lecture seule
                                        └─►  Coach (NOUVEAU, /mcp-coach/mcp, jeton)        lit/écrit les fichiers
                                                     │ écrit (validé, commité)
 Navigateur ──► Traefik ──► /coach (mot de passe) ──►  site  ◄── lit ──  /home/<utilisateur>/coach-data (git privé)
```

| Élément | Où | Accès |
|---|---|---|
| Site | `https://<ton-domaine>.freeboxos.fr/coach/` | mot de passe (basicAuth Traefik), HTTPS Let's Encrypt |
| API MCP | `https://<ton-domaine>.freeboxos.fr/mcp-coach/mcp` | jeton `X-Api-Key` obligatoire (le serveur refuse de démarrer sans) |
| Données | `/home/<utilisateur>/coach-data` | dépôt git privé, un commit `[mobile]` par écriture |

## Ce que l'API peut — et ne peut pas
- **Peut** : lire `activities/ medical/ nutrition/ planning/ rapports/ resources/` ; écrire (sans `resources/`) un fichier `.md` dont le
  bloc `arc` passe la validation ; modifier une séance (`update_session`) ou une valeur du profil (`set_profile`, liste blanche
  bornée) ; passer les garde-fous ; consulter l'historique ; **annuler son dernier changement**.
- **Ne peut pas** : lire ou écrire `config/` (verrou médical, identifiants), supprimer un fichier, sortir de la liste blanche
  (`..`, chemins absolus, liens symboliques refusés), écrire un fichier invalide, annuler un commit qui n'est pas le sien,
  écrire dans Nightscout, pousser sur Garmin (le push d'entraînements reste sur le Mac : `garmin-mcp` y a ses jetons).
- Limites : 200 Ko par fichier, 30 écritures / 5 min.

## Mise en place (une fois)
1. **Migrer les données** (Mac → Freebox, simulation par défaut) :
   `FREEBOX_SSH=<utilisateur>@<ip-freebox> deploy/freebox/migrate-from-mac.sh` (simulation), puis la même commande avec `--yes`. Rien n'est supprimé côté Mac.
2. **Cloner le dépôt** sur la Freebox : `git clone https://github.com/Lobwick/ai-bike-coach.git ~/ai-bike-coach` (code seul, sans données).
3. **Secrets** : `cd ~/ai-bike-coach/deploy/freebox && cp .env.example .env && chmod 600 .env`, puis renseigner
   `COACH_MCP_TOKEN` (`openssl rand -hex 32`) et `COACH_BASIC_AUTH` (`htpasswd -nbB <utilisateur> 'mot-de-passe'`, entre apostrophes).
4. **Lancer** : `sudo docker compose up -d --build` (réseau externe `web` et Traefik déjà en place).
5. **Vérifier** : `curl -s https://<ton-domaine>.freeboxos.fr/mcp-coach/health` → `{"ok":true}` ; le site demande le mot de passe ;
   sans en-tête `X-Api-Key`, `/mcp-coach/mcp` répond 401.
6. **Connecteur claude.ai** (sur claude.ai ou l'appli, Paramètres → Connecteurs → Ajouter un connecteur personnalisé) :
   URL `https://<ton-domaine>.freeboxos.fr/mcp-coach/mcp`, en-tête personnalisé `X-Api-Key` = le jeton.

## Utilisation depuis le mobile
Demande par exemple : « utilise le coach, regarde ma semaine et décale la sortie du jeudi à vendredi », « mets mon FTP à 245 »,
« lance une synchro : lis mes séances dans Open Wearables, ma glycémie dans Nightscout, et enregistre-les ». Claude mobile commence par
`get_instructions("contract")` (format des fichiers) puis écrit via l'API ; le site se met à jour tout seul.
**Une « mise à jour » est donc faite par Claude mobile avec ses connecteurs** : rien ne fait tourner de modèle sur la Freebox.

## Sécurité (à connaître)
- Le site et l'API exposent des **données de santé** sur Internet : mot de passe fort, jeton long, HTTPS obligatoire. Pour couper
  l'accès : `sudo docker compose stop`.
- Les secrets sont dans `.env` (non versionné, `chmod 600`) ; ne jamais en mettre dans `compose.yaml` ni dans un dépôt.
  des clés en clair ; les déplacer dans un `.env` est recommandé (et d'éviter de sauvegarder ce fichier dans un dépôt).
- Le site refuse de démarrer hors boucle locale sans `ARC_ALLOWED_HOSTS` et `ARC_PROXY_AUTH=1` (qui déclare un proxy authentifiant).
- Annuler : `undo_last_change` (mobile) ou `git -C ~/coach-data revert <commit>`. Tout changement est dans `git log`.

## Maintenance
- Mettre le code à jour : `git pull && sudo docker compose up -d --build`.
- Sauvegarde : `~/coach-data` est un dépôt git ; ajouter un remote **privé** et pousser (`git -C ~/coach-data push`).
- Le Mac reste utilisable : `git pull` du dépôt de données (`rsync` inverse) avant une session Claude Code, puis repousser.
