# Profil — `poids` (perte de poids)

Chargé par `coach-poids`.

## Cadre
- Perte visée 0,25-0,75 %/semaine, plafond 1 % (garde-fou R6). Déficit modéré 300-500 kcal/j
  (`[weight_loss].default_deficit_kcal`). Nul en semaine de course, d'affûtage, de blessure.
- ≤ 300 kcal de déficit les jours de séance clé (garde-fou R7).
- Protéines ≥ 1,8 g/kg/j. Glucides suivent la charge. Jamais de coupe du ravitaillement sur le vélo
  pendant une séance > 90 min.
- Énergie disponible plancher : 30 kcal/kg de masse maigre/j (`arc_weight.py ea`).
- IMC cible < 18,5 : ne pas planifier, orienter vers un médecin.

## Mesures (Open Wearables)
`get_timeseries` : `weight`, `body_fat_percentage`, `body_mass_index`. On raisonne sur la **tendance**
(moyenne exponentielle, `arc_weight.py trend`), jamais sur une pesée isolée. Masse grasse
balance/montre = estimation grossière.

## Fichiers
`rapports/AAAA-MM-JJ_poids.md` (hebdo), `nutrition/AAAA-MM-JJ_nutrition.md` (jour),
`planning/AAAA-MM-JJ_decision_<slug>.md` (changement de déficit).
