#!/usr/bin/env python3
"""Normalisation des données Open Wearables (MCP agrégateur).

Open Wearables fusionne plusieurs sources (Garmin, Whoop, Apple Santé, Strava…) :
la MÊME sortie y apparaît souvent 2 à 4 fois, avec des champs complémentaires et
des valeurs incohérentes (calories, allure). Ce script — pur, stdlib, sans réseau —
rend un jeu de séances dédoublonné que les agents persistent ensuite en Markdown.

    python3 scripts/arc_ow.py workouts  < workout_events.json   # séances dédoublonnées
    python3 scripts/arc_ow.py daily     < timeseries.json       # FC repos / HRV / poids par jour
    python3 scripts/arc_ow.py sleep     < sleep_summary.json    # une nuit par date
    python3 scripts/arc_ow.py activity  < activity_summary.json # résumé quotidien (0 = absent)
    python3 scripts/arc_ow.py hr --start ISO --end ISO < hr_timeseries.json   # FC d'une séance, dédoublonnée

Entrée : la réponse JSON brute de l'outil MCP (ou sa liste `records`).
Options : --tz Europe/Paris   --priority garmin,strava,whoop,apple

Règles (« approximations du projet », dites telles quelles) :
- Deux enregistrements sont la même séance si leurs départs sont à ≤ 3 min et leurs
  durées à ≤ 10 % (ou ≤ 120 s) d'écart. La source la mieux classée fournit la base,
  les champs absents sont complétés par les autres.
- Un enregistrement qui en CHEVAUCHE plusieurs sans leur correspondre (ex. un bloc
  Whoop couvrant deux sorties) est une `envelope` : listée, `counted: false`,
  jamais additionnée à la charge.
- `avg_pace_sec_per_km` n'a pas de sens à vélo : remplacée par `avg_speed_kmh`.
- Les calories divergent d'une source à l'autre : toutes sont conservées dans
  `calories_by_source`, jamais sommées ; `calories_kcal` suit `CALORIE_ORDER`.
- Une mesure absente reste absente (clé omise), jamais 0.
- Les doublons sont devenus rares côté Open Wearables mais pas nuls : ce passage est idempotent,
  sans effet quand il n'y a rien à fusionner. Le lancer toujours.
- Résumé quotidien : `0` kcal / pas / distance = donnée ABSENTE (jour sans synchronisation), jamais une
  vraie valeur nulle. Les séries horaires `active_energy`/`basal_energy` ne servent pas à reconstituer un
  total (valeurs cumulées à la synchronisation, doublons) : utiliser `total_kcal` du résumé quotidien.
"""
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

DEFAULT_PRIORITY = ["garmin", "strava", "whoop", "apple"]
CALORIE_ORDER = ["whoop", "garmin", "apple", "strava"]  # strava sous-déclare souvent
START_TOL_S = 180
DUR_TOL_RATIO = 0.10
DUR_TOL_ABS_S = 120
FIELDS = {"distance_meters": "distance_m", "elevation_gain_meters": "elevation_gain_m",
          "avg_heart_rate_bpm": "avg_hr_bpm", "max_heart_rate_bpm": "max_hr_bpm"}
SPORT_FAMILY = {
    "cycling": "cycling", "indoor_cycling": "cycling", "virtual_cycling": "cycling",
    "road_cycling": "cycling", "gravel_cycling": "cycling",
    "mountain_biking": "cycling", "cyclocross": "cycling", "e_biking": "cycling",
    "generic": "generic",
}


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _records(doc):
    if isinstance(doc, list):
        return doc
    return doc.get("records", [])


def _local_date(dt, tz):
    if tz and ZoneInfo:
        return dt.astimezone(ZoneInfo(tz)).date().isoformat()
    return dt.date().isoformat()


def _rank(source, priority):
    return priority.index(source) if source in priority else len(priority)


def _same_session(a, b):
    if SPORT_FAMILY.get(a["type"], a["type"]) != SPORT_FAMILY.get(b["type"], b["type"]):
        return False
    if abs((a["_s"] - b["_s"]).total_seconds()) > START_TOL_S:
        return False
    da, db = a["duration_seconds"], b["duration_seconds"]
    return abs(da - db) <= max(DUR_TOL_ABS_S, DUR_TOL_RATIO * max(da, db))


def _overlap_s(a, b):
    lo, hi = max(a["_s"], b["_s"]), min(a["_e"], b["_e"])
    return max(0.0, (hi - lo).total_seconds())


def workouts(doc, tz="Europe/Paris", priority=None):
    priority = priority or DEFAULT_PRIORITY
    recs = []
    for r in _records(doc):
        if not r.get("start_datetime") or not r.get("duration_seconds"):
            continue
        r = dict(r)
        r["_s"], r["_e"] = _dt(r["start_datetime"]), _dt(r["end_datetime"])
        recs.append(r)
    recs.sort(key=lambda r: (r["_s"], _rank(r.get("source"), priority)))

    clusters = []
    for r in recs:
        for c in clusters:
            if _same_session(c[0], r):
                c.append(r)
                break
        else:
            clusters.append([r])

    sessions = []
    for c in clusters:
        c.sort(key=lambda r: _rank(r.get("source"), priority))
        base = c[0]
        s = {
            "date": _local_date(base["_s"], tz),
            "start": base["start_datetime"],
            "end": base["end_datetime"],
            "duration_s": int(base["duration_seconds"]),
            "sport": base["type"],
            "sources": sorted({x.get("source") for x in c}, key=lambda x: _rank(x, priority)),
            "ow_ids": [x["id"] for x in c],
            "counted": True,
        }
        for f, key in FIELDS.items():
            for x in c:
                if x.get(f) is not None:
                    s[key] = x[f]
                    break
        cal = {x["source"]: x["calories_kcal"] for x in c if x.get("calories_kcal") is not None}
        if cal:
            s["calories_by_source"] = cal
            for src in CALORIE_ORDER:
                if src in cal:
                    s["calories_kcal"] = round(cal[src])
                    break
        if s.get("distance_m"):
            s["avg_speed_kmh"] = round(s["distance_m"] / s["duration_s"] * 3.6, 1)
        sessions.append(s)

    # enveloppes : un enregistrement qui en chevauche ≥ 1 autre sans lui correspondre
    # est déjà un cluster à part ; on le marque s'il couvre ≥ 50 % d'une autre séance.
    for s in sessions:
        s_start, s_end = _dt(s["start"]), _dt(s["end"])
        covered = []
        for o in sessions:
            if o is s:
                continue
            o_start, o_end = _dt(o["start"]), _dt(o["end"])
            ov = max(0.0, (min(s_end, o_end) - max(s_start, o_start)).total_seconds())
            if ov >= 0.5 * o["duration_s"] and s["duration_s"] > o["duration_s"] * 1.1:
                covered.append(o)
        if covered:
            s["counted"] = False
            s["envelope_of"] = [f"{o['date']} {o['start'][11:16]}Z" for o in covered]
    sessions.sort(key=lambda s: s["start"])
    return {
        "sessions": sessions,
        "raw_records": len(recs),
        "duplicates_removed": len(recs) - len(sessions),
        "envelopes": sum(1 for s in sessions if not s["counted"]),
    }


def sleep(doc, tz="Europe/Paris", priority=None):
    priority = priority or DEFAULT_PRIORITY
    by_date = defaultdict(list)
    for r in _records(doc):
        by_date[r["date"]].append(r)
    nights = []
    for date in sorted(by_date):
        rs = sorted(by_date[date], key=lambda r: (_rank(r.get("source"), priority),
                                                  -(r.get("duration_minutes") or 0)))
        b = rs[0]
        n = {"date": date, "duration_min": b.get("duration_minutes"),
             "start": b.get("start_datetime"), "end": b.get("end_datetime"),
             "source": b.get("source")}
        if len(rs) > 1:
            n["other_sources"] = {x["source"]: x.get("duration_minutes") for x in rs[1:]}
        for k in ("deep_minutes", "rem_minutes", "light_minutes", "awake_minutes", "efficiency"):
            if b.get(k) is not None:
                n[k] = b[k]
        nights.append({k: v for k, v in n.items() if v is not None})
    return {"nights": nights}


def daily(doc, tz="Europe/Paris", priority=None):
    """FC de repos (min du jour), HRV (moyenne), poids/masse grasse (dernière valeur)."""
    priority = priority or DEFAULT_PRIORITY
    buckets = defaultdict(lambda: defaultdict(list))
    for r in _records(doc):
        d = _local_date(_dt(r["timestamp"]), tz)
        buckets[d][r["type"]].append(r)
    out = []
    for d in sorted(buckets):
        row = {"date": d}
        for t, rs in buckets[d].items():
            best = min(_rank(x.get("source"), priority) for x in rs)
            rs = [x for x in rs if _rank(x.get("source"), priority) == best]
            vals = [x["value"] for x in rs]
            if t == "resting_heart_rate":
                # les échantillons horaires contiennent des artefacts (jour/nuit) : on prend
                # le minimum plausible du jour, la médiane serait tirée par les pics.
                row["resting_hr_bpm"] = min(vals)
            elif t.startswith("heart_rate_variability"):
                row[t.replace("heart_rate_variability_", "hrv_") + "_ms"] = round(statistics.mean(vals), 1)
            elif t in ("respiratory_rate", "oxygen_saturation"):
                row[{"respiratory_rate": "respiratory_rate_brpm", "oxygen_saturation": "spo2_pct"}[t]] = \
                    round(statistics.mean(vals), 1)
            elif t in ("active_energy", "basal_energy"):
                continue  # séries horaires non fiables : voir `activity`
            elif t in ("weight", "body_fat_percentage", "body_mass_index"):
                last = max(rs, key=lambda x: x["timestamp"])["value"]
                row[{"weight": "weight_kg", "body_fat_percentage": "body_fat_pct",
                     "body_mass_index": "bmi"}[t]] = last
            else:
                row[t] = round(statistics.mean(vals), 2)
            row.setdefault("sources", {})[t] = rs[0].get("source")
        out.append(row)
    return {"days": out}


def activity(doc, tz="Europe/Paris", priority=None):
    """Résumé quotidien : les valeurs nulles d'énergie/pas/distance sont ABSENTES (omises)."""
    priority = priority or DEFAULT_PRIORITY
    by = {}
    for r in _records(doc):
        by.setdefault(r["date"], []).append(r)
    days = []
    for date in sorted(by):
        r = sorted(by[date], key=lambda x: _rank(x.get("source"), priority))[0]
        d = {"date": date, "source": r.get("source")}
        for k, key in (("steps", "steps"), ("distance_meters", "distance_m"),
                       ("active_calories_kcal", "active_kcal"), ("total_calories_kcal", "total_kcal"),
                       ("active_minutes", "active_min"), ("elevation_meters", "elevation_gain_m")):
            if r.get(k):
                d[key] = round(r[k], 1) if isinstance(r[k], float) else r[k]
        hr = r.get("heart_rate") or {}
        for k in ("avg", "max", "min"):
            if hr.get(f"{k}_bpm"):
                d[f"hr_{k}_bpm"] = hr[f"{k}_bpm"]
        im = r.get("intensity_minutes") or {}
        if any(im.values()):
            d["intensity_minutes"] = {k: v for k, v in im.items() if v}
        if "total_kcal" not in d:
            d["energy_missing"] = True
        days.append(d)
    return {"days": days}


def hr_series(doc, start, end, priority=None):
    """Échantillons de FC d'une fenêtre, un point par horodatage (moyenne des enregistrements
    simultanés, y compris d'une même source), triés. Résolution estimée par la médiane des écarts."""
    s, e = _dt(start), _dt(end)
    buckets = defaultdict(list)
    for r in _records(doc):
        if r.get("type") != "heart_rate":
            continue
        t = _dt(r["timestamp"])
        if s <= t <= e:
            buckets[t].append(r["value"])
    pts = [{"t": t.isoformat(), "bpm": round(sum(v) / len(v), 1)} for t, v in sorted(buckets.items())]
    gaps = sorted((_dt(b["t"]) - _dt(a["t"])).total_seconds() for a, b in zip(pts, pts[1:]))
    return {"samples": pts, "n": len(pts), "resolution_s": int(gaps[len(gaps) // 2]) if gaps else None,
            "note": "FC moyennée par intervalle : la valeur maximale d'un intervalle sous-estime le vrai pic"}


def main(argv):
    if len(argv) < 2 or argv[1] not in ("workouts", "sleep", "daily", "activity", "hr"):
        print(__doc__)
        return 2
    tz, prio, win = "Europe/Paris", None, {}
    args = argv[2:]
    while args:
        a = args.pop(0)
        if a == "--tz":
            tz = args.pop(0)
        elif a == "--priority":
            prio = args.pop(0).split(",")
        elif a in ("--start", "--end"):
            win[a[2:]] = args.pop(0)
        elif a == "--file":
            sys.stdin = open(args.pop(0), encoding="utf-8")
    doc = json.load(sys.stdin)
    if argv[1] == "hr":
        print(json.dumps(hr_series(doc, win["start"], win["end"], prio), ensure_ascii=False, indent=2))
        return 0
    fn = {"workouts": workouts, "sleep": sleep, "daily": daily, "activity": activity}[argv[1]]
    print(json.dumps(fn(doc, tz, prio), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
