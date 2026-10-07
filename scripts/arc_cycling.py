#!/usr/bin/env python3
"""Charge d'entraînement, zones et forme pour le vélo (route, cyclocross).

    python3 scripts/arc_cycling.py zones   [--profile planning/Athlete_Profile.md]
    python3 scripts/arc_cycling.py load    [--days 90] [--until AAAA-MM-JJ] [--workspace .]
    python3 scripts/arc_cycling.py session --duration-s 3600 [--np-w 220 | --avg-hr 150 | --rpe 6]
    python3 scripts/arc_cycling.py hr-load --timeseries ts.json --start ISO --end ISO

Vocabulaire GÉNÉRIQUE (comme dans tout le projet) : *charge* (par séance), *condition*
(moyenne exponentielle 42 j), *fatigue* (7 j), *forme* = condition − fatigue. On ne
reprend pas les sigles déposés TSS/CTL/ATL/TSB dans les fichiers ni les réponses.

Charge d'une séance, par ordre de précédence — la méthode est toujours tracée :
  power : 100 × h × (NP/FTP)²                          (FTP au profil)
  hr_series : 100 × Σ TRIMP(intervalle) / TRIMP(1 h au seuil)  (série de FC Open Wearables, la meilleure
              méthode sans puissance : capte les intervalles que la FC moyenne écrase)
  hr    : même formule sur la FC MOYENNE de la séance (repli quand la série manque)
  rpe   : 100 × h × IF(RPE)²                           (table ci-dessous)
Aucune méthode possible → pas de charge (jamais 0).  Tous les barèmes sont des
« approximations du projet », pas des mesures de laboratoire. Une FC moyenne
sous-estime une séance à intervalles (la charge réelle est plus haute).
"""
import datetime as dt
import glob
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arc_contract  # noqa: E402
import coach_config  # noqa: E402

# Zones de puissance (% FTP), modèle à 7 zones.
POWER_ZONES = [
    ("Z1", "Récupération active", 0.0, 0.55),
    ("Z2", "Endurance", 0.56, 0.75),
    ("Z3", "Tempo", 0.76, 0.90),
    ("Z4", "Seuil", 0.91, 1.05),
    ("Z5", "VO2max", 1.06, 1.20),
    ("Z6", "Capacité anaérobie", 1.21, 1.50),
    ("Z7", "Neuromusculaire", 1.51, None),
]
# Zones de FC à vélo (% LTHR), modèle à 7 zones.
HR_ZONES = [
    ("Z1", 0.0, 0.81), ("Z2", 0.81, 0.89), ("Z3", 0.90, 0.93), ("Z4", 0.94, 0.99),
    ("Z5a", 1.00, 1.02), ("Z5b", 1.03, 1.06), ("Z5c", 1.06, None),
]
# Facteur d'intensité approché par RPE (échelle 1-10) et par intensité planifiée.
IF_BY_RPE = {1: .45, 2: .50, 3: .60, 4: .70, 5: .78, 6: .85, 7: .92, 8: 1.0, 9: 1.08, 10: 1.15}
IF_BY_INTENSITY = {"rest": 0.0, "recovery": .55, "endurance": .68, "tempo": .80,
                   "threshold": .95, "vo2max": 1.08, "anaerobic": 1.15,
                   "race": 1.0, "strength": .50}


def power_zones(ftp):
    return [{"zone": z, "name": n, "low_w": round(lo * ftp),
             "high_w": round(hi * ftp) if hi else None} for z, n, lo, hi in POWER_ZONES]


def hr_zones(lthr):
    return [{"zone": z, "low_bpm": round(lo * lthr),
             "high_bpm": round(hi * lthr) if hi else None} for z, lo, hi in HR_ZONES]


def trimp(hr, hr_rest, hr_max, minutes, sex="m"):
    """TRIMP exponentiel de Banister (1991)."""
    x = max(0.0, min(1.0, (hr - hr_rest) / (hr_max - hr_rest)))
    a, b = (0.86, 1.67) if sex == "f" else (0.64, 1.92)
    return minutes * x * a * math.exp(b * x)


def estimate_lthr(hr_rest, hr_max):
    """Repli quand le seuil n'est pas mesuré : ~85 % de la réserve de FC."""
    return hr_rest + 0.85 * (hr_max - hr_rest)


def session_load(duration_s, profile=None, np_w=None, avg_power_w=None,
                 avg_hr=None, rpe=None):
    """Retourne (charge, méthode) ou (None, None) si aucune méthode n'est possible."""
    p = profile or {}
    h = duration_s / 3600.0
    if np_w or avg_power_w:
        ftp = p.get("ftp_w")
        if ftp:
            w = np_w or avg_power_w
            return round(100 * h * (w / ftp) ** 2, 1), "power"
    if avg_hr and p.get("hr_rest_bpm") and p.get("hr_max_bpm"):
        rest, mx = p["hr_rest_bpm"], p["hr_max_bpm"]
        lthr = p.get("lthr_bpm") or estimate_lthr(rest, mx)
        ref = trimp(lthr, rest, mx, 60, p.get("sex", "m"))
        if ref > 0:
            return round(100 * trimp(avg_hr, rest, mx, duration_s / 60, p.get("sex", "m")) / ref, 1), "hr"
    if rpe:
        f = IF_BY_RPE.get(int(round(rpe)))
        if f:
            return round(100 * h * f * f, 1), "rpe"
    return None, None


def hr_series_load(samples, profile, resolution_s=None):
    """samples : [{"t": ISO, "bpm": x}] (sortie de `arc_ow.py hr`). Retourne un dict ou None."""
    p = profile or {}
    if len(samples) < 3 or not (p.get("hr_rest_bpm") and p.get("hr_max_bpm")):
        return None
    rest, mx, sex = p["hr_rest_bpm"], p["hr_max_bpm"], p.get("sex", "m")
    lthr = p.get("lthr_bpm") or estimate_lthr(rest, mx)
    ref = trimp(lthr, rest, mx, 60, sex)
    if not resolution_s:
        ts = [dt.datetime.fromisoformat(s["t"]) for s in samples]
        gaps = sorted((b - a).total_seconds() for a, b in zip(ts, ts[1:]))
        resolution_s = gaps[len(gaps) // 2]
    minutes = resolution_s / 60.0
    total, zones = 0.0, {}
    for s in samples:
        total += trimp(s["bpm"], rest, mx, minutes, sex)
        z = next((n for n, lo, hi in HR_ZONES if s["bpm"] >= lo * lthr and (hi is None or s["bpm"] < hi * lthr)), "Z1")
        zones[z] = zones.get(z, 0) + minutes
    half = len(samples) // 2
    a1 = sum(s["bpm"] for s in samples[:half]) / half
    a2 = sum(s["bpm"] for s in samples[half:]) / (len(samples) - half)
    easy = sum(v for z, v in zones.items() if z in ("Z1", "Z2"))
    return {"load": round(100 * total / ref, 1), "load_method": "hr_series",
            "avg_hr_bpm": round(sum(s["bpm"] for s in samples) / len(samples)),
            "peak_interval_hr_bpm": round(max(s["bpm"] for s in samples)),
            "time_in_zone_min": {k: round(v) for k, v in sorted(zones.items())},
            "easy_share_pct": round(100 * easy / sum(zones.values())),
            "hr_drift_pct": round(100 * (a2 - a1) / a1, 1),
            "lthr_bpm_used": round(lthr), "lthr_is_estimate": not p.get("lthr_bpm"),
            "resolution_s": int(resolution_s), "n": len(samples),
            "note": "dérive = 2e moitié vs 1re ; non interprétable sur un parcours vallonné ou des intervalles"}


def planned_load(duration_s, intensity):
    f = IF_BY_INTENSITY.get(intensity)
    if f is None:
        return None
    return round(100 * duration_s / 3600.0 * f * f, 1)


def series(daily_loads, start, end, cond_days=42, fatigue_days=7):
    """daily_loads : {date_iso: charge}. Une journée sans séance = charge 0.
    Retourne une liste de jours avec condition/fatigue/forme de FIN de journée."""
    kc, kf = 1 - math.exp(-1 / cond_days), 1 - math.exp(-1 / fatigue_days)
    cond = fat = 0.0
    out, d = [], start
    while d <= end:
        load = daily_loads.get(d.isoformat(), 0.0)
        cond += (load - cond) * kc
        fat += (load - fat) * kf
        out.append({"date": d.isoformat(), "load": round(load, 1),
                    "condition": round(cond, 1), "fatigue": round(fat, 1),
                    "form": round(cond - fat, 1)})
        d += dt.timedelta(days=1)
    return out


def read_profile(path):
    try:
        with open(path, encoding="utf-8") as fh:
            obj = arc_contract.extract(fh.read())
        return obj or {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_activities(root):
    """Séances au contrat : {date: [obj…]} depuis activities/*.md (blocs arc `activity`)."""
    acts = []
    for path in sorted(glob.glob(os.path.join(root, "activities", "*.md"))):
        try:
            with open(path, encoding="utf-8") as fh:
                obj = arc_contract.extract(fh.read())
        except (OSError, json.JSONDecodeError):
            continue
        if obj and obj.get("type") == "activity" and obj.get("date"):
            obj["_file"] = os.path.relpath(path, root)
            acts.append(obj)
    return acts


def build_daily(acts, profile):
    daily, missing = {}, []
    for a in acts:
        load, method = a.get("load"), a.get("load_method")
        if load is None:
            load, method = session_load(a["duration_s"], profile, a.get("np_w"),
                                        a.get("avg_power_w"), a.get("avg_hr_bpm"), a.get("rpe"))
        if load is None:
            missing.append(a["_file"])
            continue
        daily[a["date"]] = daily.get(a["date"], 0.0) + load
    return daily, missing


def current_state(root, until=None, days=90, cfg=None):
    cfg = cfg or coach_config.load(root)
    profile = read_profile(os.path.join(root, coach_config.get(cfg, "athlete.profile",
                                                               "planning/Athlete_Profile.md")))
    acts = read_activities(root)
    daily, missing = build_daily(acts, profile)
    end = until or dt.date.today()
    # on part de la 1re séance connue pour que la moyenne exponentielle ait sa mémoire
    first = min([dt.date.fromisoformat(d) for d in daily] or [end])
    ser = series(daily, min(first, end - dt.timedelta(days=days)), end,
                 coach_config.get(cfg, "load.condition_days", 42),
                 coach_config.get(cfg, "load.fatigue_days", 7))
    history_days = (end - first).days + 1 if daily else 0
    state = ser[-1] if ser else None
    ramp = None
    if len(ser) > 7:
        ramp = round(ser[-1]["condition"] - ser[-8]["condition"], 1)
    return {"as_of": end.isoformat(), "history_days": history_days,
            "reliable": history_days >= 42, "state": state, "ramp_per_week": ramp,
            "series": ser[-days:], "sessions_without_load": missing,
            "profile_has": sorted(k for k in profile if k != "type")}


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, args = argv[1], argv[2:]
    opt = {}
    while args:
        a = args.pop(0)
        if a.startswith("--"):
            opt[a[2:]] = args.pop(0) if args and not args[0].startswith("--") else True
    root = opt.get("workspace", coach_config.ROOT)
    if cmd == "zones":
        prof = read_profile(os.path.join(root, opt.get("profile", "planning/Athlete_Profile.md")))
        out = {}
        if prof.get("ftp_w"):
            out["power"] = power_zones(prof["ftp_w"])
            if prof.get("weight_kg"):
                out["w_per_kg"] = round(prof["ftp_w"] / prof["weight_kg"], 2)
        if prof.get("lthr_bpm"):
            out["hr"] = hr_zones(prof["lthr_bpm"])
        if not out:
            out["error"] = "ni ftp_w ni lthr_bpm au profil — ne rien inventer, les demander"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if "error" not in out else 1
    if cmd == "hr-load":
        import arc_ow
        prof = read_profile(os.path.join(root, "planning/Athlete_Profile.md"))
        with open(opt["timeseries"], encoding="utf-8") as fh:
            ser = arc_ow.hr_series(json.load(fh), opt["start"], opt["end"])
        res = hr_series_load(ser["samples"], prof, ser["resolution_s"])
        if res is None:
            res = {"error": "série trop courte ou profil sans FC repos/max : repli sur la FC moyenne (session) ou le RPE"}
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 1 if "error" in res else 0
    if cmd == "session":
        prof = read_profile(os.path.join(root, "planning/Athlete_Profile.md"))
        load, method = session_load(
            float(opt.get("duration-s", 0)), prof,
            float(opt["np-w"]) if "np-w" in opt else None,
            float(opt["avg-power-w"]) if "avg-power-w" in opt else None,
            float(opt["avg-hr"]) if "avg-hr" in opt else None,
            float(opt["rpe"]) if "rpe" in opt else None)
        print(json.dumps({"load": load, "load_method": method}, ensure_ascii=False))
        return 0 if load is not None else 1
    if cmd == "load":
        until = dt.date.fromisoformat(opt["until"]) if "until" in opt else None
        print(json.dumps(current_state(root, until, int(opt.get("days", 90))),
                         ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
