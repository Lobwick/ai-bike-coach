---
name: weather-forecast
description: Prévisions météo (wttr.in via WebFetch) pour la sortie ou la course — résolution du lieu, catégories 🟢🟡🟠🔴, créneau optimal (matin tôt / midi / soir) par séance extérieure. Utilisé par les coachs à chaque validation de semaine ou de jour.
---

# Météo des sorties

- **Lieu** (précédence stricte) : override dans le fichier de la semaine > `planning/active_objective.md` >
  lieu par défaut du profil > demander. Sans lieu, ne devine pas.
- **Source** : WebFetch `https://wttr.in/<lieu>?format=j1` (3 jours). Persiste `medical/AAAA-MM-JJ_meteo.md`
  si utile ; une prévision n'est pas une mesure.
- **Catégories vélo** : 🟢 sec, 5-27 °C, vent < 30 km/h · 🟡 pluie légère, 2-5 °C ou 27-32 °C, vent 30-40 ·
  🟠 pluie soutenue, < 2 °C, > 32 °C, vent > 40 · 🔴 orage, verglas/neige sur route, > 35 °C, vent > 55.
  🔴 route : proposer l'intérieur (home trainer), jamais un forcing.
- **Cyclo-cross** : pluie/boue/gel changent la séance (technique plutôt que relances à fond sur terrain
  gelé), jamais la sécurité ; note le terrain attendu (boue, sec, sable) pour pneus et pressions.
- **Chaleur** : chaleur ≥ 28 °C = intensité à la FC (inchangée) plutôt qu'à la puissance, hydratation +,
  créneau matinal ; pas d'intensité maintenue en 🔴.
- **Créneau** : propose matin tôt / midi / soir selon température et vent, et dis pourquoi en une phrase.
