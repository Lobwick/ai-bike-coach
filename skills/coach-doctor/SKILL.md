---
name: coach-doctor
description: Diagnostic d'installation en une commande (/coach-doctor) — validité de la configuration, profil complet, MCP Open Wearables et Garmin déclarés, historique exploitable, fichiers hors contrat. À charger dès qu'un symptôme d'installation apparaît, avant de deviner la cause.
---

# /coach-doctor

`python3 scripts/coach_doctor.py [--json]` : vérifie la configuration TOML, la cohérence agents/disciplines,
le profil (FTP/LTHR/poids…), la présence des fichiers de contrat, l'historique de charge, les serveurs MCP
déclarés (`.mcp.json` pour `garmin`, liste blanche **en écriture seulement**), et signale l'accès à
Open Wearables à vérifier depuis la session (ce script n'appelle aucun réseau). Ne lit ni n'écrit rien de
sensible. Lis la sortie, explique chaque ✗/⚠ en une ligne, propose le correctif.
