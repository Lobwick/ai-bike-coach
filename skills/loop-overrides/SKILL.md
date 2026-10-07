---
name: loop-overrides
description: Commande /override — analyse les préréglages d'override Loop (vus dans Nightscout, ex. « sport », « long », « stop ») à la lumière des séances vélo réelles, et PROPOSE des hypothèses de réglage ou la création d'un nouveau préréglage. Lecture seule : ne crée, ne modifie et n'active jamais un override, ne dose rien. L'athlète applique dans l'app Loop après avis de son équipe de diabétologie. Nécessite [glucose].enabled.
---

# /override — proposer, jamais appliquer

Actif seulement si `[glucose].enabled = true`. Charge aussi `nightscout-glucose`.

## Pourquoi on ne l'applique pas nous-mêmes (à dire à l'athlète)
1. Les préréglages sont **définis dans l'app Loop** ; Nightscout n'en détient qu'une copie écrite par Loop. Modifier
   cette copie ne change pas ce que Loop fait et sera écrasé au prochain envoi.
2. Cette copie est le même document que les **basales, la sensibilité et les ratios** : un `update_nightscout_profile`
   raté ou erroné touche tout ce qui pilote l'insuline.
3. Un facteur d'insuline ou une cible d'override, c'est de l'**insuline** : la décision est celle de l'athlète et de son
   équipe de diabétologie. Un agent n'active ni ne programme un override (`log_treatment` interdit), même « pour aider ».
Si l'athlète insiste pour que l'agent écrive ou active, rappelle ces trois raisons une fois, propose plutôt de préparer la
fiche à reporter dans Loop, et ne passe pas outre.

## Procédure
1. **Préréglages actuels** : `get_current_profile` (lecture). Sauvegarde la réponse dans un fichier temporaire du
   scratchpad, puis `python3 scripts/arc_override.py presets --profile <fichier>` : seuls nom, symbole, facteur
   d'insuline, plage cible et durée sortent. **Ne recopie jamais** `deviceToken`, basales, sensibilité, ratios ni limites
   de dosage dans une réponse, un fichier du dépôt ou un commit ; supprime le fichier temporaire ensuite.
2. **Activations** : `get_treatments_by_date` (30 jours, `count` élevé ; le résultat peut être très gros : lis le
   fichier avec python, pas à l'écran) → `arc_override.py activations --treatments <fichier> --days 30`.
   Les doublons (commandes à distance à la même minute) sont fusionnés par le script.
3. **Séances** : les activités vélo des 30 derniers jours (`activities/`, `ow_ids`). Pour chacune,
   `get_glucose_by_date_range` (début − 15 min → fin + 2 h) et `arc_glucose.py session` ; ajoute `window.start/end`.
   Rassemble les sorties en un `sessions.json` (liste).
4. **Analyse** : `arc_override.py analyze --sessions … --activations … --presets …`.
5. **Présente** (tableau) : un préréglage par ligne — séances, hypoglycémies, départs < 90, pics ≥ 250, avance médiane
   d'activation —, puis les `proposals`. Chaque proposition est une **hypothèse** (`status: "hypothèse"`) avec son
   évidence, son pas minuscule et la mention « à valider avec ton équipe de diabétologie ». Dis les limites :
   `< 3 séances` = pas de chiffre ; l'intensité, l'adrénaline (départs de cyclo-cross), la nourriture et l'insuline
   active brouillent la lecture ; corrélation ≠ causalité.
6. **Nouveau préréglage** : si des séances sans override montrent des hypoglycémies ou des départs bas (`creer_ou_utiliser`),
   ou si un type de séance n'a pas de préréglage adapté (ex. course de cyclo-cross vs sortie longue), propose-le en
   décrivant le contexte d'usage, un nom, un symbole et, pour point de départ, une COPIE d'un préréglage existant — jamais
   des chiffres inventés. Un préréglage inutilisé (`unused_presets`, ex. « long ») est signalé : peut-être pertinent
   pour les sorties longues, à lui de dire.
7. **Trace** : `planning/AAAA-MM-JJ_decision_override-<slug>.md` (type `decision`, `trigger: "override_proposal"`,
   `outcome: "proposed"`, `before`/`after` = valeurs courantes et candidates). `applied` seulement quand l'athlète dit qu'il
   l'a modifié dans Loop. Valide avec `arc_contract.py --validate`.
8. **Après coup** : propose de relire les mêmes indicateurs sur les ≥ 3 séances suivantes (`/override`) pour voir l'effet.

## Timing (information, jamais une consigne)
Dans la fiche d'une séance, tu peux rappeler « ton préréglage habituel pour ce format : sport (0,41 ; 150-160) » d'après
l'historique, et la médiane d'avance d'activation observée. L'activation reste l'affaire de l'athlète.

## Jamais
Écrire/activer un override, `log_treatment`, `update_nightscout_profile`, proposer une dose, un bolus, une basale, un ratio,
une sensibilité ou une limite de dosage ; sortir des bornes du script (pas de ± 0,05 de facteur, ± 10 mg/dL de cible).
Ce n'est pas un avis médical.
