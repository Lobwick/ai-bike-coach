#!/usr/bin/env python3
"""Synchronisation de l'historique Open Wearables → fichiers `activities/` (contrat `arc`).

    python3 scripts/arc_sync.py activities --workouts w.json [--power p.json] [--since 2026-07-01] [--dry-run]
    python3 scripts/arc_sync.py health --daily d.json [--sleep s.json] [--since 2026-07-01] [--dry-run]

Entrées : la réponse JSON brute de `get_workout_events` et (facultatif) de `get_timeseries(types=["power"], resolution="1min")`.
Pur, stdlib, sans réseau. N'écrase JAMAIS un fichier existant (fusion manuelle si besoin).

Règles (« approximations du projet », dites telles quelles dans chaque fichier) :
- Séances dédoublonnées par `arc_ow.workouts` ; seules les séances de vélo sont écrites (marche, ménage, course à pied… listées
  dans le rapport comme ignorées) ; une `envelope` n'est jamais comptée.
- Enregistrement oublié (> 3 h à moins de 6 km/h de moyenne) ou < 5 min : ignoré et signalé, jamais compté en charge.
- Charge : puissance (si ≥ 60 % de la durée est couverte) > FC moyenne > aucune. Jamais d'invention : une séance sans puissance
  ni FC n'a pas de charge (clé omise).
- `np_w` est une ESTIMATION faite à partir de moyennes d'1 minute (la vraie NP lisse sur 30 s) : elle sous-estime légèrement ;
  la durée utilisée pour la charge est celle où la puissance est mesurée (arrêts exclus).
- La provenance de la puissance (capteur ou estimation de la plateforme) n'est pas distinguable dans Open Wearables.
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arc_contract  # noqa: E402
import arc_cycling  # noqa: E402
import arc_ow  # noqa: E402
import coach_config  # noqa: E402

CYCLING = {"cycling", "indoor_cycling", "virtual_cycling", "road_cycling", "gravel_cycling", "mountain_biking", "cyclocross"}
MIN_DURATION_S = 300
FORGOTTEN_MIN_H = 3
FORGOTTEN_MAX_KMH = 6.0
POWER_COVERAGE = 0.60


def intensity_from_if(f):
    for lim, name in ((0.55, "recovery"), (0.75, "endurance"), (0.90, "tempo"), (1.05, "threshold"), (1.20, "vo2max")):
        if f < lim:
            return name
    return "anaerobic"


def _dt(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def power_for(session, power_records):
    s, e = _dt(session["start"]), _dt(session["end"])
    vals = sorted((r["timestamp"], r["value"]) for r in power_records if s <= _dt(r["timestamp"]) <= e)
    return [v for _, v in vals]


def power_stats(vals, duration_s):
    n = len(vals)
    if n < 10 or n * 60 < POWER_COVERAGE * duration_s:
        return None
    avg = sum(vals) / n
    np_est = (sum(v ** 4 for v in vals) / n) ** 0.25
    return {"n": n, "avg_w": round(avg), "np_w": round(np_est), "measured_s": n * 60, "coverage_pct": round(100 * n * 60 / duration_s)}


def build_activity(s, vals, profile, power_ok):
    a = {"type": "activity", "date": s["date"], "discipline": "route", "duration_s": s["duration_s"],
         "ow_ids": s["ow_ids"], "sources": s["sources"]}
    for k in ("distance_m", "elevation_gain_m", "avg_hr_bpm", "max_hr_bpm", "calories_kcal"):
        if s.get(k):
            a[k] = round(s[k], 1) if isinstance(s[k], float) else s[k]
    ps = power_stats(vals, s["duration_s"]) if power_ok else None
    if ps:
        a["avg_power_w"], a["np_w"] = ps["avg_w"], ps["np_w"]
        ftp = profile.get("ftp_w")
        if ftp:
            load = round(100 * (ps["measured_s"] / 3600) * (ps["np_w"] / ftp) ** 2, 1)
            a["load"], a["load_method"] = load, "power"
            a["intensity"] = intensity_from_if(ps["np_w"] / ftp)
    if "load" not in a:
        load, method = arc_cycling.session_load(s["duration_s"], profile, avg_hr=a.get("avg_hr_bpm"))
        if load is not None:
            a["load"], a["load_method"] = load, method
    return a, ps


def body(s, a, ps):
    h, m = divmod(round(s["duration_s"] / 60), 60)
    L = [f"Sortie vélo du {s['date']} — {h} h {m:02d} (synchronisée depuis Open Wearables, source : {', '.join(s['sources'])})."]
    if a.get("distance_m"):
        L.append(f"Distance {a['distance_m'] / 1000:.1f} km, vitesse moyenne {s.get('avg_speed_kmh', '—')} km/h"
                 + (f", D+ {round(a['elevation_gain_m'])} m." if a.get("elevation_gain_m") else "."))
    if a.get("avg_hr_bpm"):
        L.append(f"FC moyenne {a['avg_hr_bpm']} bpm" + (f", maximale {a['max_hr_bpm']} bpm." if a.get("max_hr_bpm") else "."))
    if ps:
        L.append(f"Puissance moyenne {ps['avg_w']} W, NP estimée {ps['np_w']} W (moyennes d'1 min : légèrement sous-estimée), "
                 f"mesurée sur {ps['coverage_pct']} % de la durée. Charge {a.get('load', '—')} (méthode : puissance, arrêts exclus).")
    elif "load" in a:
        L.append(f"Pas de puissance sur cette séance : charge {a['load']} estimée depuis la FC moyenne "
                 "(sous-estime une séance à intervalles). ")
    else:
        L.append("Ni puissance ni FC : charge non calculée (mesure absente, jamais remplacée par 0).")
    L.append("Discipline : « route » par défaut (Open Wearables ne distingue pas le cyclo-cross) ; à corriger si cette sortie en était un.")
    return "\n\n".join(L)


def sync_activities(workouts_doc, power_doc, root, since=None, dry_run=False, tz="Europe/Paris"):
    profile = arc_cycling.read_profile(os.path.join(root, "planning", "Athlete_Profile.md"))
    res = arc_ow.workouts(workouts_doc, tz)
    power = (power_doc or {}).get("records", [])
    report = {"written": [], "skipped_existing": [], "ignored": [], "no_load": [], "power": {"sessions": 0}, "profile_ftp_w": profile.get("ftp_w")}
    per_day = {}
    for s in sorted(res["sessions"], key=lambda x: x["start"]):
        if since and s["date"] < since:
            continue
        why = None
        sport = s["sport"]
        if sport not in CYCLING:
            why = f"hors vélo ({sport})"
        elif not s["counted"]:
            why = "enveloppe (bloc qui en recouvre d'autres)"
        elif s["duration_s"] < MIN_DURATION_S:
            why = "moins de 5 min"
        elif s["duration_s"] > FORGOTTEN_MIN_H * 3600 and (s.get("distance_m") or 0) / s["duration_s"] * 3.6 < FORGOTTEN_MAX_KMH:
            why = f"enregistrement probablement oublié ({s['duration_s'] // 3600} h à {(s.get('distance_m') or 0) / s['duration_s'] * 3.6:.1f} km/h)"
        if why:
            report["ignored"].append({"date": s["date"], "start": s["start"][11:16] + "Z", "why": why})
            continue
        vals = power_for(s, power)
        a, ps = build_activity(s, vals, profile, power_ok=True)
        n = per_day.get(s["date"], 0)
        per_day[s["date"]] = n + 1
        name = f"{s['date']}_route.md" if n == 0 else f"{s['date']}_route_{n + 1}.md"
        path = os.path.join(root, "activities", name)
        if os.path.exists(path):
            report["skipped_existing"].append(name)
            continue
        text = f"# Sortie vélo — {s['date']}\n\n```arc\n{json.dumps(a, ensure_ascii=False, indent=1)}\n```\n\n{body(s, a, ps)}\n"
        errs = arc_contract.validate_obj(a)
        if errs:
            report["ignored"].append({"date": s["date"], "why": f"contrat invalide : {errs}"})
            continue
        if not dry_run:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        report["written"].append({"file": name, "load": a.get("load"), "method": a.get("load_method"), "min": round(s["duration_s"] / 60)})
        if ps:
            report["power"]["sessions"] += 1
        if "load" not in a:
            report["no_load"].append(name)
    ld = [w["load"] for w in report["written"] if w["load"] is not None]
    report["summary"] = {"written": len(report["written"]), "with_load": len(ld), "by_method": {m: sum(1 for w in report["written"] if w["method"] == m)
                                                                                                       for m in ("power", "hr", "rpe")},
                         "ignored": len(report["ignored"]), "dry_run": dry_run}
    return report


HEALTH_KEYS = ("resting_hr_bpm", "hrv_rmssd_ms", "weight_kg", "body_fat_pct", "respiratory_rate_brpm", "spo2_pct")


def sync_health(daily_doc, sleep_doc, root, since=None, dry_run=False, tz="Europe/Paris"):
    """Un `medical/AAAA-MM-JJ_health.md` par jour ayant au moins une mesure. AUCUN verdict : il appartient au bilan matinal."""
    days = {d["date"]: d for d in arc_ow.daily(daily_doc, tz)["days"]} if daily_doc else {}
    nights = {n["date"]: n for n in arc_ow.sleep(sleep_doc, tz)["nights"]} if sleep_doc else {}
    report = {"written": [], "skipped_existing": [], "days_without_data": 0, "metrics": {}}
    for date in sorted(set(days) | set(nights)):
        if since and date < since:
            continue
        h = {"type": "health", "date": date}
        d = days.get(date, {})
        for k in HEALTH_KEYS:
            if d.get(k):
                h[k] = d[k]
        if date in nights and nights[date].get("duration_min"):
            h["sleep_min"] = nights[date]["duration_min"]
        measured = [k for k in h if k not in ("type", "date")]
        if not measured:
            report["days_without_data"] += 1
            continue
        for k in measured:
            report["metrics"][k] = report["metrics"].get(k, 0) + 1
        path = os.path.join(root, "medical", f"{date}_health.md")
        if os.path.exists(path):
            report["skipped_existing"].append(date)
            continue
        errs = arc_contract.validate_obj(h)
        if errs:
            report.setdefault("invalid", []).append({"date": date, "errors": errs})
            continue
        L = ["Mesures du jour issues d'Open Wearables (une valeur absente est absente, jamais lue comme normale) :"]
        if "resting_hr_bpm" in h:
            L.append(f"- FC de repos : {h['resting_hr_bpm']} bpm (minimum du matin).")
        if "hrv_rmssd_ms" in h:
            L.append(f"- HRV (rmssd) : {h['hrv_rmssd_ms']} ms.")
        if "sleep_min" in h:
            L.append(f"- Sommeil : {h['sleep_min'] // 60} h {h['sleep_min'] % 60:02d} (source : {nights[date].get('source')}).")
        if "weight_kg" in h:
            L.append(f"- Poids : {h['weight_kg']} kg (une pesée isolée ne décide rien : on suit la tendance).")
        for k, lab, u in (("respiratory_rate_brpm", "Fréquence respiratoire", "/min"), ("spo2_pct", "SpO₂", "%"), ("body_fat_pct", "Masse grasse (estimation)", "%")):
            if k in h:
                L.append(f"- {lab} : {h[k]} {u}.")
        L.append("\nPas de verdict ici : le bilan matinal (vert / orange / rouge) est rendu par le coach, jamais déduit d'une mesure seule.")
        if not dry_run:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"# Bilan santé — {date}\n\n```arc\n{json.dumps(h, ensure_ascii=False, indent=1)}\n```\n\n" + "\n".join(L) + "\n")
        report["written"].append(date)
    report["summary"] = {"written": len(report["written"]), "dry_run": dry_run}
    return report


def main(argv):
    if len(argv) >= 2 and argv[1] == "health":
        opt, a = {}, argv[2:]
        while a:
            k = a.pop(0)
            if k == "--dry-run":
                opt["dry"] = True
            elif k.startswith("--"):
                opt[k[2:]] = a.pop(0)
        load = lambda p: json.load(open(p, encoding="utf-8"))  # noqa: E731
        rep = sync_health(load(opt["daily"]) if "daily" in opt else None, load(opt["sleep"]) if "sleep" in opt else None,
                          opt.get("workspace", coach_config.ROOT), opt.get("since"), bool(opt.get("dry")))
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0
    if len(argv) < 2 or argv[1] != "activities":
        print(__doc__)
        return 2
    opt, a = {}, argv[2:]
    while a:
        k = a.pop(0)
        if k == "--dry-run":
            opt["dry"] = True
        elif k.startswith("--"):
            opt[k[2:]] = a.pop(0)
    load = lambda p: json.load(open(p, encoding="utf-8"))  # noqa: E731
    rep = sync_activities(load(opt["workouts"]), load(opt["power"]) if "power" in opt else None,
                          opt.get("workspace", coach_config.ROOT), opt.get("since"), bool(opt.get("dry")))
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
