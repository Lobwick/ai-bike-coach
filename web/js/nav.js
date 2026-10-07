// Sections du tableau de bord : une seule liste, lue par app.js.
export function navItems(settings) {
  return [
    ["", "Aujourd'hui"], ["forme", "Forme & charge"], ["sante", "Santé"], ["semaine", "Semaine"],
    ["seances", "Séances"], ["calendrier", "Calendrier"], ["decisions", "Décisions"],
    ...(settings?.disciplines?.includes("poids") ? [["poids", "Poids"]] : []),
  ];
}
