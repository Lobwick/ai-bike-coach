#!/usr/bin/env python3
"""Diagnostic d'installation — statique, aucun appel réseau, rien de sensible lu.

    python3 scripts/coach_doctor.py [--json]

Code de sortie : 0 si aucun ✗, 1 sinon.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arc_contract  # noqa: E402
import arc_cycling  # noqa: E402
import coach_config  # noqa: E402

ROOT = coach_config.ROOT
PUSH_TOOLS = {"schedule_workouts", "schedule_week", "upload_workout", "get_scheduled_workouts",
              "get_workout_by_id", "get_workouts", "unschedule_workout", "unschedule_workouts",
              "delete_workout", "create_strength_workout"}
KNOWN_AGENTS = {"coach-route", "coach-cx", "coach-poids", "medical", "nutritionist"}
DISC_AGENT = {"route": "coach-route", "cx": "coach-cx", "poids": "coach-poids"}


def checks():
    out = []

    def add(level, name, msg):
        out.append({"level": level, "check": name, "message": msg})

    try:
        cfg = coach_config.load(ROOT)
        add("ok", "config", "workspace.toml (+ user) lisible")
    except Exception as e:  # noqa: BLE001
        add("error", "config", f"TOML illisible : {e}")
        return out

    if coach_config.get(cfg, "data.source") != "openwearables":
        add("error", "data_source", "[data].source doit valoir « openwearables »")
    else:
        add("ok", "data_source", "source de lecture : Open Wearables")
    if coach_config.get(cfg, "push.target") != "garmin":
        add("warn", "push_target", "[push].target ≠ garmin : aucun push d'entraînement possible")
    if not coach_config.get(cfg, "data.ow_user_id"):
        add("warn", "ow_user_id", "[data].ow_user_id vide : le coach appellera get_users à chaque session (/coach-setup)")

    enabled = set(coach_config.get(cfg, "agents.enabled", []) or [])
    unknown = enabled - KNOWN_AGENTS
    if unknown:
        add("error", "agents", f"agents inconnus : {sorted(unknown)}")
    for d in coach_config.get(cfg, "sport.disciplines", []) or []:
        if DISC_AGENT.get(d) and DISC_AGENT[d] not in enabled:
            add("warn", "agents", f"discipline « {d} » sans agent {DISC_AGENT[d]} dans [agents].enabled")
        if not os.path.exists(os.path.join(ROOT, "config", "sports", f"{d}.md")):
            add("error", "sports", f"config/sports/{d}.md manquant")
    for a in enabled & KNOWN_AGENTS:
        if not os.path.exists(os.path.join(ROOT, "agents", f"{a}.md")):
            add("error", "agents", f"agents/{a}.md manquant")

    # profil
    ppath = os.path.join(ROOT, coach_config.get(cfg, "athlete.profile", "planning/Athlete_Profile.md"))
    if not os.path.exists(ppath):
        add("warn", "profile", f"{os.path.relpath(ppath, ROOT)} absent : lancer /coach-setup")
    else:
        errs = arc_contract.validate_file(ppath)
        if errs:
            add("error", "profile", "; ".join(errs))
        else:
            prof = arc_cycling.read_profile(ppath)
            missing = [k for k in ("ftp_w", "lthr_bpm", "hr_max_bpm", "hr_rest_bpm", "weight_kg") if k not in prof]
            if missing:
                add("warn", "profile", f"valeurs absentes (jamais inventées) : {missing}")
            else:
                add("ok", "profile", "profil complet")
            if "ftp_w" not in prof and "lthr_bpm" not in prof:
                add("warn", "targets", "ni FTP ni LTHR : les séances poussées n'auront pas de cible chiffrée")
    # MCP Garmin : lecture interdite
    mcp = os.path.join(ROOT, ".mcp.json")
    if os.path.exists(mcp):
        try:
            servers = json.load(open(mcp)).get("mcpServers", {})
        except json.JSONDecodeError:
            servers = {}
            add("error", "mcp", ".mcp.json invalide")
        g = servers.get("garmin")
        if g:
            tools = set((g.get("env", {}).get("GARMIN_ENABLED_TOOLS") or "").split(",")) - {""}
            extra = tools - PUSH_TOOLS
            if extra:
                add("error", "garmin_whitelist", f"outils de LECTURE exposés (interdits) : {sorted(extra)}")
            elif tools:
                add("ok", "garmin_whitelist", "garmin limité aux outils de push")
            else:
                add("warn", "garmin_whitelist", "GARMIN_ENABLED_TOOLS vide : tous les outils seraient exposés")
        else:
            add("warn", "mcp", "serveur garmin absent de .mcp.json : aucun push possible (./install.sh)")
    else:
        add("warn", "mcp", ".mcp.json absent : lancer ./install.sh")
    add("info", "open_wearables", "connecteur Open Wearables à vérifier en session (get_users) — non testé ici")

    gl = cfg.get("glucose", {})
    if gl.get("enabled"):
        add("info", "glucose", "Nightscout actif (lecture seule) — vérifier en session : server_status / get_current_glucose")
        wl = cfg.get("weight_loss", {})
        if "poids" in (coach_config.get(cfg, "sport.disciplines", []) or []) \
                and not wl.get("medical_clearance_required"):
            add("warn", "weight_loss", "glycémie suivie mais [weight_loss].medical_clearance_required = false : "
                "un déficit sous insuline exige l'accord du médecin")
        elif wl.get("medical_clearance_required") and not wl.get("medical_clearance_confirmed"):
            add("info", "weight_loss", "verrou médical actif : aucun déficit planifié tant que medical_clearance_confirmed = false")
    # historique / fichiers
    st = arc_cycling.current_state(ROOT)
    if st["history_days"] < 42:
        add("warn", "history", f"historique de charge {st['history_days']} j (< 42) : R1/R2/R4 non évaluées")
    else:
        add("ok", "history", f"historique de charge {st['history_days']} j")
    if st["sessions_without_load"]:
        add("warn", "load", f"{len(st['sessions_without_load'])} séance(s) sans charge calculable (profil ou RPE manquant)")
    bad = []
    for sub in ("activities", "medical", "nutrition", "rapports"):
        for p in glob.glob(os.path.join(ROOT, sub, "*.md")):
            if "```arc" not in open(p, encoding="utf-8").read():
                bad.append(os.path.relpath(p, ROOT))
            elif arc_contract.validate_file(p):
                bad.append(os.path.relpath(p, ROOT))
    if bad:
        add("warn", "contract", f"{len(bad)} fichier(s) hors contrat (ex. anciens fichiers course à pied) : "
            f"{bad[:3]}{'…' if len(bad) > 3 else ''}")
    else:
        add("ok", "contract", "fichiers conformes au contrat")
    return out


def main(argv):
    res = checks()
    if "--json" in argv:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        icon = {"ok": "✓", "warn": "⚠", "error": "✗", "info": "ℹ"}
        for r in res:
            print(f"{icon[r['level']]} {r['check']}: {r['message']}")
    return 1 if any(r["level"] == "error" for r in res) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
