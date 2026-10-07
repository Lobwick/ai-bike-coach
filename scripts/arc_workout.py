#!/usr/bin/env python3
"""Construit le `workout_data` Garmin (DTO) d'une séance vélo — le seul usage de Garmin ici.

    python3 scripts/arc_workout.py templates
    python3 scripts/arc_workout.py template sweet_spot --duration-s 4500 [--ftp 250] [--lthr 170]
    python3 scripts/arc_workout.py build --spec spec.json          # spec libre (voir ci-dessous)
    python3 scripts/arc_workout.py validate < workout.json

Spec libre :
  {"name": "...", "description": "...", "steps": [
     {"kind": "warmup|interval|recovery|cooldown|rest", "duration_s": 600,
      "power_w": [180, 210]  |  "hr_bpm": [140, 152]  |  "cadence_rpm": [90, 100],
      "description": "..."},
     {"repeat": 4, "steps": [ {...}, {...} ]}
  ]}

Cibles : `power_w` si le FTP est connu, sinon `hr_bpm` ; jamais une valeur inventée —
sans FTP ni LTHR, le pas part sans cible (`no.target`) et la description porte la
consigne en RPE. Schéma DTO : mêmes clés que le skill garmin-workout-scheduling
(`workoutSegments`/`workoutSteps`/`endConditionValue`, jamais `steps`/`conditionValue`).

⚠ Les identifiants de cible de PUISSANCE (power.zone = 2) et de CADENCE (cadence.zone = 3)
viennent du catalogue Garmin Connect, pas d'un push vérifié par ce projet : après le
PREMIER push, relire le séance (`get_workout_by_id`) et contrôler les watts à l'œil.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arc_cycling  # noqa: E402
import coach_config  # noqa: E402

SPORT = {"sportTypeId": 2, "sportTypeKey": "cycling"}
STEP_TYPES = {"warmup": (1, "warmup"), "cooldown": (2, "cooldown"), "interval": (3, "interval"),
              "recovery": (4, "recovery"), "rest": (5, "rest")}
TARGETS = {"none": (1, "no.target"), "power": (2, "power.zone"),
           "cadence": (3, "cadence.zone"), "hr": (4, "heart.rate.zone")}


def _step(order, s):
    kind = s.get("kind", "interval")
    sid, skey = STEP_TYPES[kind]
    d = {"type": "ExecutableStepDTO", "stepOrder": order,
         "stepType": {"stepTypeId": sid, "stepTypeKey": skey},
         "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
         "endConditionValue": int(s["duration_s"])}
    if s.get("description"):
        d["description"] = s["description"]
    for key, tkey in (("power_w", "power"), ("hr_bpm", "hr"), ("cadence_rpm", "cadence")):
        if s.get(key):
            lo, hi = s[key]
            if lo > hi:
                raise ValueError(f"cible {key} : borne basse {lo} > haute {hi}")
            tid, tname = TARGETS[tkey]
            d["targetType"] = {"workoutTargetTypeId": tid, "workoutTargetTypeKey": tname}
            d["targetValueOne"], d["targetValueTwo"] = int(lo), int(hi)
            break
    else:
        tid, tname = TARGETS["none"]
        d["targetType"] = {"workoutTargetTypeId": tid, "workoutTargetTypeKey": tname}
    return d


def _steps(items, counter):
    out = []
    for s in items:
        counter[0] += 1
        if "repeat" in s:
            order = counter[0]
            inner = _steps(s["steps"], counter)
            out.append({"type": "RepeatGroupDTO", "stepOrder": order,
                        "numberOfIterations": int(s["repeat"]),
                        "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
                        "endConditionValue": int(s["repeat"]),
                        "workoutSteps": inner})
        else:
            out.append(_step(counter[0], s))
    return out


def build(spec):
    steps = _steps(spec["steps"], [0])
    return {"workoutName": spec["name"], "description": spec.get("description", ""),
            "sportType": SPORT,
            "workoutSegments": [{"segmentOrder": 1, "sportType": SPORT, "workoutSteps": steps}]}


def total_seconds(spec_steps):
    t = 0
    for s in spec_steps:
        t += s["repeat"] * total_seconds(s["steps"]) if "repeat" in s else s["duration_s"]
    return t


def _tgt(ftp, lthr, pct, spread=0.03, hr_pct=None):
    """Cible puissance (±spread) si FTP, sinon FC si LTHR, sinon aucune."""
    if ftp:
        return {"power_w": [round(ftp * (pct - spread)), round(ftp * (pct + spread))]}
    if lthr and hr_pct:
        return {"hr_bpm": [round(lthr * hr_pct[0]), round(lthr * hr_pct[1])]}
    return {}


def _fit_core(duration_s, warm, cool):
    return max(duration_s - warm - cool, 0)


def template(name, duration_s, ftp=None, lthr=None):
    w, c = 600, 300
    core = _fit_core(duration_s, w, c)
    wu = {"kind": "warmup", "duration_s": w, "description": "Échauffement progressif, cadence libre",
          **_tgt(ftp, lthr, .55, .08, (.70, .80))}
    cd = {"kind": "cooldown", "duration_s": c, "description": "Retour au calme, très facile",
          **_tgt(ftp, lthr, .45, .08, (.60, .70))}
    easy = lambda t, d: {"kind": "recovery", "duration_s": t, "description": d,  # noqa: E731
                         **_tgt(ftp, lthr, .50, .08, (.60, .75))}
    steps, nm = None, None
    if name == "endurance":
        nm = "Endurance Z2"
        steps = [{"kind": "interval", "duration_s": duration_s - 0,
                  "description": "Z2 régulière, conversation possible, cadence 85-95",
                  **_tgt(ftp, lthr, .65, .09, (.81, .89))}]
    elif name == "sweet_spot":
        nm = "Sweet spot"
        reps = max(2, core // (720 + 300))
        steps = [wu, {"repeat": reps, "steps": [
            {"kind": "interval", "duration_s": 720, "description": "88-93 % FTP, régulier",
             **_tgt(ftp, lthr, .90, .03, (.90, .93))}, easy(300, "Souple, pédaler léger")]}, cd]
    elif name == "threshold":
        nm = "Seuil"
        reps = max(2, core // (600 + 300))
        steps = [wu, {"repeat": reps, "steps": [
            {"kind": "interval", "duration_s": 600, "description": "95-105 % FTP",
             **_tgt(ftp, lthr, 1.0, .05, (.97, 1.01))}, easy(300, "Récupération")]}, cd]
    elif name == "vo2max":
        nm = "VO2max 3 min"
        reps = max(4, core // (180 + 180))
        steps = [wu, {"repeat": reps, "steps": [
            {"kind": "interval", "duration_s": 180, "description": "110-120 % FTP, dur mais tenable",
             **_tgt(ftp, lthr, 1.13, .035, (1.03, 1.06))}, easy(180, "Très souple")]}, cd]
    elif name == "cx_race_sim":
        nm = "CX simulation course (relances)"
        reps = max(4, core // 300)
        steps = [wu, {"repeat": reps, "steps": [
            {"kind": "interval", "duration_s": 20, "description": "Relance de sortie de virage / obstacle, ≥ 150 % FTP",
             **_tgt(ftp, lthr, 1.6, .15, None)},
            {"kind": "interval", "duration_s": 220, "description": "Tour à allure de course, 100-108 % FTP",
             **_tgt(ftp, lthr, 1.04, .04, (1.00, 1.04))},
            easy(60, "Souple — équivalent d'une zone de récup / technique")]}, cd]
    elif name == "cx_starts":
        nm = "CX départs"
        steps = [wu, {"repeat": 6, "steps": [
            {"kind": "interval", "duration_s": 15, "description": "Départ : sprint max puis tenir ~10 s",
             **_tgt(ftp, lthr, 2.0, .3, None)},
            easy(285, "Récupération complète, technique douce")]}, cd]
    else:
        raise ValueError(f"gabarit inconnu : {name}")
    spec = {"name": nm, "description": f"{nm} — {round(total_seconds(steps) / 60)} min", "steps": steps}
    return spec


TEMPLATES = ["endurance", "sweet_spot", "threshold", "vo2max", "cx_race_sim", "cx_starts"]


def validate(dto):
    errs = []
    for k in ("workoutName", "sportType", "workoutSegments"):
        if k not in dto:
            errs.append(f"clé manquante : {k}")
    for bad in ("steps", "conditionValue"):
        if bad in json.dumps(dto) and f'"{bad}"' in json.dumps(dto):
            errs.append(f"clé interdite (400 Garmin) : {bad}")

    def walk(steps, path):
        for i, s in enumerate(steps):
            w = f"{path}[{i}]"
            if s.get("type") == "RepeatGroupDTO":
                if not s.get("numberOfIterations"):
                    errs.append(f"{w}: numberOfIterations manquant")
                walk(s.get("workoutSteps", []), w + ".workoutSteps")
            elif s.get("type") == "ExecutableStepDTO":
                if "endConditionValue" not in s and s["endCondition"]["conditionTypeKey"] != "lap.button":
                    errs.append(f"{w}: endConditionValue manquant")
                if "targetValueOne" in s and s["targetValueOne"] > s["targetValueTwo"]:
                    errs.append(f"{w}: cible basse > haute")
            else:
                errs.append(f"{w}: type de pas inconnu")
    for seg in dto.get("workoutSegments", []):
        walk(seg.get("workoutSteps", []), "workoutSteps")
    return errs


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, a, opt = argv[1], argv[2:], {}
    pos = []
    while a:
        k = a.pop(0)
        if k.startswith("--"):
            opt[k[2:]] = a.pop(0)
        else:
            pos.append(k)
    if cmd == "templates":
        print(json.dumps(TEMPLATES))
        return 0
    if cmd == "template":
        prof = arc_cycling.read_profile(os.path.join(coach_config.ROOT, "planning/Athlete_Profile.md"))
        ftp = float(opt["ftp"]) if "ftp" in opt else prof.get("ftp_w")
        lthr = float(opt["lthr"]) if "lthr" in opt else prof.get("lthr_bpm")
        spec = template(pos[0], int(opt.get("duration-s", 3600)), ftp, lthr)
        out = {"workout_data": build(spec), "targets_from": "power" if ftp else "hr" if lthr else "none",
               "duration_s": total_seconds(spec["steps"])}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if cmd == "build":
        spec = json.load(open(opt["spec"]) if opt.get("spec") not in (None, "-") else sys.stdin)
        print(json.dumps(build(spec), ensure_ascii=False, indent=2))
        return 0
    if cmd == "validate":
        errs = validate(json.load(sys.stdin))
        print(json.dumps({"ok": not errs, "errors": errs}, ensure_ascii=False))
        return 1 if errs else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
