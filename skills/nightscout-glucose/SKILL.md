---
name: nightscout-glucose
description: Lecture de la glycémie (CGM) et des traitements via le MCP Nightscout, en LECTURE SEULE, autour des séances vélo — contrôle avant départ, analyse pendant/après, bilan du jour, hypoglycémies tardives. Charger dès que [glucose].enabled est vrai et qu'une séance, un ravitaillement ou un bilan est en jeu. Jamais de dose, jamais d'écriture.
---

# Glycémie (Nightscout) — lecture seule

Actif seulement si `[glucose].enabled = true`. Sinon : aucune lecture, aucune mention.

## Limites non négociables
- **Outils autorisés (lecture)** : `get_current_glucose`, `get_recent_glucose`, `get_glucose_by_date_range`,
  `get_daily_glucose_stats`, `get_glucose_stats_batch`, `calculate_time_in_range`, `analyze_glucose_patterns`,
  `get_recent_treatments`, `get_treatments_by_date`, `get_insulin_on_board`, `get_latest_device_status`,
  `get_current_profile` (lecture), `server_status`. Le préfixe dépend du client (`mcp__nightscout__…`).
- **Interdits, toujours** : `log_treatment`, `remove_treatment`, `update_nightscout_profile`. Un glucide ou un
  repas déclaré à l'athlète se note dans nos fichiers ; s'il veut l'enregistrer dans Loop/Nightscout, **il le
  fait lui-même**.
- **Aucune dose, aucune correction, aucun changement de basale, de ratio, de cible ou d'override Loop.** Tu
  décris, tu rappelles des repères de consensus, tu renvoies la décision à l'athlète et à son équipe de
  diabétologie. Une glycémie < 54 mg/dL, des hypoglycémies répétées, des cétones, ou une anomalie du capteur →
  recommander de contacter l'équipe soignante. Dis « ce n'est pas un avis médical ».
- **Vie privée** : la glycémie est une donnée de santé sensible. Jamais de valeur brute dans un fichier destiné
  à un dépôt public ; les fichiers du workspace sont gitignorés.
- **Mesure absente ≠ normale** : capteur hors service, bruit élevé ou trou de données → « indisponible ».

## Overrides Loop
Lecture des préréglages et de l'historique d'activation pour analyse et propositions : skill `loop-overrides`. Le profil
Nightscout contient aussi basales, sensibilité, ratios et jeton d'appareil : n'en extrais que les préréglages
(`arc_override.py presets`), ne les recopie jamais.

## Avant une séance — `python3 scripts/arc_glucose.py precheck`
`get_current_glucose` (valeur + flèche de tendance) → `precheck --mgdl V --direction D --intensity I --duration-s S`.
Retour : catégorie (`hypo` < 70, `bas` < 90, `limite_basse` < 126, `cible` 126-180, `haute_acceptable` ≤ 250, `haute`),
glucides à prendre avant (fourchette), message. Tendance descendante = prévoir plus de glucides. Optionnel :
`get_insulin_on_board` pour signaler une insuline active importante (information seulement).
Ces repères viennent d'un consensus (Riddell 2017) : « approximations du projet ». Si la valeur est `hypo`/`bas`, la
séance **attend** ; ne propose jamais « tu peux y aller quand même ».

## Pendant et après — `python3 scripts/arc_glucose.py session`
`get_glucose_by_date_range` (début − 15 min → fin + 2 h) et `get_treatments_by_date` → sauvegarde les JSON bruts
en fichiers temporaires (scratchpad) → `session --start … --end … --glucose g.json --treatments t.json`.
Écris dans l'activité : `glucose_start_mgdl`, `glucose_min_mgdl`, `glucose_max_mgdl`, `glucose_end_mgdl`,
`glucose_post_min_mgdl`, `hypo_events`, `carbs_logged_g`, `loop_override` (raison de l'override actif, ex. « 🚴 sport »).
Dans le texte : tendance pendant l'effort (pente mg/dL/h), hypoglycémie éventuelle, ravitaillement réel vs prévu.
Rappelle que le risque d'hypoglycémie tardive (nuit suivante) dure jusqu'à ~24 h après un effort long ou intense.
Un override Loop « sport » est une décision de l'athlète : constate-le, ne le critique ni ne le modifie.

## Bilan du jour
`get_daily_glucose_stats` (ou `calculate_time_in_range`) → dans `medical/AAAA-MM-JJ_health.md` :
`glucose_avg_mgdl`, `tir_pct`, `time_below_pct`, `time_above_pct`, `glucose_cv_pct`, `lows_below_54`,
`nocturnal_low` (vrai si < 70 la nuit précédente). Sur une semaine ou plus : `get_glucose_stats_batch` (pas de
boucle de lectures brutes). `analyze_glucose_patterns` pour les motifs par heure — présentés comme des
observations à discuter avec l'équipe de diabétologie, jamais comme un réglage à appliquer.

## Principes d'entraînement (informatifs, jamais prescriptifs)
Un effort aérobie continu tend à faire baisser la glycémie ; des efforts très brefs et intenses (départs de
cyclo-cross, sprints) et l'adrénaline de la compétition tendent à la faire monter, parfois suivie d'une baisse
tardive. Les séances longues exigent des glucides rapides sur soi. Planifier une séance clé le matin à jeun ou juste
après un bolus important n'est pas un choix du coach : demande à l'athlète comment il gère cela avec son équipe.
