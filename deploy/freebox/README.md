# Déploiement sur la Freebox : site + MCP du coach (skills, outils, fichiers)

Objectif : depuis **Claude mobile** (ou n'importe quel client MCP), suivre les mêmes procédures que sur le Mac, répondre aux questions du
coach, modifier le plan, enregistrer les données, et **voir le résultat sur le site** sans rien relancer. Les fichiers vivent sur la
Freebox (dépôt git privé) ; le site les relit à chaque chargement (rechargement automatique toutes les 30 s).

```
 Claude mobile ──(connecteurs)──► Open Wearables  (existant)   lecture des séances, puissance, santé
                              ├─► Nightscout      (existant)   lecture de la glycémie
                              └─► Coach  /mcp-coach/mcp  (NOUVEAU, jeton)  skills + outils + fichiers
                                          │ écrit (validé, commité dans git)
 Navigateur ──► Traefik ──► /coach (mot de passe) ──► site ◄── lit ── /home/<utilisateur>/coach-data
```

Un seul conteneur, **un seul processus Python (bibliothèque standard, ≈ 27 Mo)**, deux ports internes : 8000 = site (mot de passe Traefik),
8001 = MCP (jeton). Le port du site ne sert jamais `/mcp` ; le port MCP ne sert jamais le site ni son API.

| Élément | Où | Accès |
|---|---|---|
| Site | `https://<ton-domaine>.freeboxos.fr/coach/` | mot de passe (basicAuth Traefik), HTTPS Let's Encrypt |
| MCP | `https://<ton-domaine>.freeboxos.fr/mcp-coach/mcp` | jeton `X-Api-Key` (le serveur refuse de démarrer sans) |
| Données | `/home/<utilisateur>/coach-data` | dépôt git privé, un commit `[mobile]` par écriture |

## Les trois couches du MCP
1. **Instructions** : `list_skills`, `get_skill` (les 12+ skills du dépôt), `get_instructions` (coachs et contrat de données) ; les skills
   sont aussi des *prompts MCP* pour les clients qui les gèrent. Un skill dit « lance `python3 scripts/…` » : sur un téléphone,
   cela n'existe pas, donc `get_skill` ajoute la consigne d'utiliser les outils ci-dessous.
2. **Outils déterministes** (ils tournent sur la Freebox) : `compute_session_load`, `get_zones`, `check_guardrails`, `build_workout`
   (gabarits Garmin avec cibles de puissance), `glucose_precheck`, `glucose_session`, `weight_plan`, `fueling`, `validate_contract`.
3. **Fichiers et ingestion** : `read_file`, `list_files`, `write_file`, `update_session`, `set_profile`, `history`, `undo_last_change`,
   `get_status`, et `ingest_activities` / `ingest_health`.

**Lecture des données.** Claude mobile lit Open Wearables et Nightscout avec leurs connecteurs, puis passe les enregistrements
**de façon compacte** à `ingest_*` (quelques jours à la fois : un gros historique se transmet mal par le téléphone). Les outils calculent la
charge (puissance > FC > effort perçu), fusionnent les doublons, n'écrasent jamais un fichier et commitent. Utilise `dry_run: true` d'abord.
Une variante « le serveur lit lui-même Open Wearables et Nightscout » (synchro par cron, sans modèle) est possible plus tard ; elle exigerait
de stocker une clé de lecture de plus dans `.env`.

## Ce que le MCP peut — et ne peut pas
- **Peut** : lire `activities/ medical/ nutrition/ planning/ rapports/ resources/`, écrire (sans `resources/`) des fichiers dont le bloc `arc`
  est valide, modifier une séance ou une valeur de profil (liste blanche bornée), passer les garde-fous, annuler son dernier changement.
- **Ne peut pas** : lire ou écrire `config/` (verrou médical, identifiants), supprimer un fichier, sortir de la liste blanche (`..`, chemins
  absolus, liens symboliques refusés), écrire un fichier invalide, annuler un commit qui n'est pas le sien, exécuter une commande, écrire
  dans Nightscout, proposer une dose d'insuline, pousser sur Garmin (voir ci-dessous).
- Limites : 200 Ko par fichier, 600 Ko par requête, 30 écritures / 5 min. Hôte et en-tête `Origin` contrôlés.

## Garmin depuis le mobile (phase 2, non déployée)
`garmin-mcp` sait servir en HTTP (`GARMIN_MCP_TRANSPORT=streamable-http`) mais **sans aucune authentification** : il ne doit JAMAIS être
exposé tel quel. Conception retenue :
- il tourne **uniquement sur le réseau interne** du conteneur, jamais derrière Traefik, avec `GARMIN_ENABLED_TOOLS` limité au push ;
- le MCP du coach est le seul à l'appeler, via un outil `garmin_push` qui (1) construit lui-même le DTO avec `build_workout` (jamais un JSON
  fourni par le modèle), (2) passe les garde-fous (un `block` refuse), (3) exige `confirmed: true` après un « oui » explicite de l'athlète
  dans la conversation, (4) vérifie l'idempotence (`get_scheduled_workouts`), pousse par lots de 4, revérifie, et note `garmin_workout_id`
  dans la semaine ;
- les identifiants Garmin (fichier `garmin_tokens.json`, mode 600) sont montés en lecture seule, hors dépôt, jamais dans l'image ;
- **prérequis mémoire** : `garmin-mcp` (Python 3.12 + SDK MCP) pèse nettement plus que le coach ; à mesurer sur la Freebox (`docker stats`)
  et à compenser en arrêtant des services Open Wearables non indispensables, avant tout déploiement.

## Mise en place (une fois)
1. **Migrer les données** (Mac → Freebox, simulation par défaut) :
   `FREEBOX_SSH=<utilisateur>@<ip-freebox> deploy/freebox/migrate-from-mac.sh` (simulation), puis la même commande avec `--yes`. Rien n'est supprimé côté Mac.
2. **Cloner le dépôt** sur la Freebox : `git clone https://github.com/Lobwick/ai-bike-coach.git ~/ai-bike-coach` (code seul, sans données).
3. **Secrets** : `cd ~/ai-bike-coach/deploy/freebox && cp .env.example .env && chmod 600 .env`, puis renseigner
   `COACH_MCP_TOKEN` (`openssl rand -hex 32`) et `COACH_BASIC_AUTH` (`htpasswd -nbB <utilisateur> 'mot-de-passe'`, entre apostrophes).
4. **Lancer** : `sudo docker compose up -d --build` (réseau externe `web` et Traefik déjà en place).
5. **Vérifier** : `curl -s https://<ton-domaine>.freeboxos.fr/mcp-coach/health` → `{"ok": true}` ; le site demande le mot de passe ;
   sans `X-Api-Key`, `/mcp-coach/mcp` répond 401 ; `sudo docker stats coach` doit afficher moins de ~50 Mo.
6. **Connecteur claude.ai** (Paramètres → Connecteurs → Ajouter un connecteur personnalisé) : URL `https://<ton-domaine>.freeboxos.fr/mcp-coach/mcp`,
   en-tête personnalisé `X-Api-Key` = le jeton. Le serveur a été testé avec le client MCP officiel ; seule la compatibilité du connecteur
   claude.ai lui-même ne peut se vérifier qu'une fois déployé.

## Utilisation depuis le mobile
« Utilise le coach : liste les skills, lance /today », « décale la sortie du jeudi à vendredi », « lance une synchro de la semaine :
lis mes séances et ma puissance dans Open Wearables, puis enregistre-les (essai à blanc d'abord) », « prépare l'ouverture de course de
jeudi (gabarit cx_opener) ». Claude commence par `list_skills`/`get_skill`, et `get_instructions("contract")` avant d'écrire.

## Sécurité (à connaître)
- Le site et le MCP exposent des **données de santé** sur Internet : mot de passe fort, jeton long, HTTPS. Couper l'accès : `sudo docker compose stop`.
- Aucun secret dans le dépôt ni dans l'image (`.dockerignore`) : tout est dans `.env` (`chmod 600`).
- Le serveur refuse de démarrer sans jeton, ou hors boucle locale sans `ARC_ALLOWED_HOSTS` et `ARC_PROXY_AUTH=1`.
- Annuler : `undo_last_change` (mobile) ou `git -C ~/coach-data revert <commit>`. Tout changement est dans `git log`.

## Maintenance
- Mettre le code à jour : `git pull && sudo docker compose up -d --build`.
- Sauvegarde : `~/coach-data` est un dépôt git ; ajouter un remote **privé** et pousser (`git -C ~/coach-data push`).
- Le Mac reste utilisable : récupérer le dépôt de données (`rsync` inverse ou `git pull`) avant une session Claude Code, puis le repousser.
