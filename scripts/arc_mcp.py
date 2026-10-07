#!/usr/bin/env python3
"""Serveur MCP du coach — bibliothèque standard uniquement, un seul processus léger (~30 Mo avec le site).

Protocole : MCP « Streamable HTTP » en mode SANS ÉTAT, réponses JSON (pas de SSE) :
`initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`, `prompts/list`, `prompts/get`.
Versions négociées : 2025-06-18, 2025-03-26, 2024-11-05.

Trois couches exposées à Claude (mobile ou bureau) :
  1. INSTRUCTIONS : skills et agents du dépôt (`list_skills`, `get_skill`, `get_instructions`, et prompts MCP) ;
  2. OUTILS : les scripts déterministes (charge, garde-fous, gabarits Garmin, glycémie, poids) — ils tournent ICI, pas sur le téléphone ;
  3. FICHIERS : lecture/écriture validées, atomiques, commitées (`arc_files_api`).

Sécurité (tout est testé) : jeton OBLIGATOIRE (le serveur refuse de démarrer sans) comparé à temps constant ; hôte et en-tête Origin
contrôlés (DNS rebinding) ; corps ≤ 400 Ko ; entrées validées contre le schéma de chaque outil ; écritures limitées (30 / 5 min) ;
aucune exécution de commande, aucun accès hors de la liste blanche de `arc_files_api` ; jamais de trace d'erreur renvoyée au client.
"""
import datetime as dt
import hmac
import http.server
import json
import logging
import os
import re
import sys
import threading
import time
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arc_contract  # noqa: E402
import arc_cycling  # noqa: E402
import arc_files_api as api  # noqa: E402
import arc_glucose  # noqa: E402
import arc_guardrails  # noqa: E402
import arc_sync  # noqa: E402
import arc_weight  # noqa: E402
import arc_workout  # noqa: E402
import coach_config  # noqa: E402

log = logging.getLogger("coach-mcp")
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_BODY = 600_000
WRITES_PER_5MIN = 30
SERVER_INFO = {"name": "ai-bike-coach", "version": "1.0.0"}
INSTRUCTIONS = ("Coach vélo (route, cyclo-cross, perte de poids). Commence par `list_skills` puis `get_skill` pour suivre la procédure "
                "voulue, et `get_instructions(\"contract\")` avant toute écriture. Lis les données d'activité dans Open Wearables et la "
                "glycémie dans Nightscout (connecteurs séparés), puis utilise ces outils pour calculer et enregistrer. Aucune dose d'insuline "
                "n'est jamais proposée ; jamais de push Garmin sans « oui » explicite.")

SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


# ------------------------------------------------------------------ validation d'entrée (sous-ensemble de JSON Schema)

def validate(value, schema, path="arguments"):
    t = schema.get("type")
    checks = {"string": str, "boolean": bool, "object": dict, "array": list}
    if t == "integer":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif t == "number":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif t in checks:
        ok = isinstance(value, checks[t]) and not (t != "boolean" and isinstance(value, bool))
    else:
        ok = True
    if not ok:
        raise RpcError(-32602, f"{path} : type {t} attendu")
    if "enum" in schema and value not in schema["enum"]:
        raise RpcError(-32602, f"{path} : valeur parmi {schema['enum']}")
    if t == "string" and len(value) > schema.get("maxLength", 200_000):
        raise RpcError(-32602, f"{path} : trop long")
    if t == "array":
        if len(value) > schema.get("maxItems", 5000):
            raise RpcError(-32602, f"{path} : trop d'éléments (max {schema.get('maxItems', 5000)})")
        for i, v in enumerate(value):
            if "items" in schema:
                validate(v, schema["items"], f"{path}[{i}]")
    if t == "object":
        for k in schema.get("required", []):
            if k not in value:
                raise RpcError(-32602, f"{path}.{k} : obligatoire")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                raise RpcError(-32602, f"{path} : champs inconnus {sorted(extra)}")
        for k, v in value.items():
            if k in props:
                validate(v, props[k], f"{path}.{k}")


def S(props=None, required=()):
    return {"type": "object", "properties": props or {}, "required": list(required), "additionalProperties": False}


STR, INT, NUM, BOOL = {"type": "string"}, {"type": "integer"}, {"type": "number"}, {"type": "boolean"}
OBJ_LIST = lambda n: {"type": "array", "items": {"type": "object"}, "maxItems": n}  # noqa: E731


# ------------------------------------------------------------------ registre d'outils

class Registry:
    def __init__(self, root):
        self.root, self.tools = root, {}
        self._writes, self._lock = deque(), threading.Lock()

    def tool(self, name, description, schema, fn, write=False):
        self.tools[name] = {"description": description, "schema": schema, "fn": fn, "write": write}

    def throttle(self):
        now = time.time()
        with self._lock:
            while self._writes and now - self._writes[0] > 300:
                self._writes.popleft()
            if len(self._writes) >= WRITES_PER_5MIN:
                raise api.ApiError(f"trop d'écritures ({WRITES_PER_5MIN} / 5 min) : réessaie plus tard")
            self._writes.append(now)

    def listing(self):
        return [{"name": n, "description": t["description"], "inputSchema": t["schema"],
                 "annotations": {"readOnlyHint": not t["write"], "destructiveHint": False, "idempotentHint": not t["write"]}}
                for n, t in sorted(self.tools.items())]

    def call(self, name, args):
        t = self.tools.get(name)
        if not t:
            raise RpcError(-32602, f"outil inconnu : {name}")
        validate(args or {}, t["schema"])
        try:
            if t["write"]:
                self.throttle()
            out = t["fn"](**(args or {}))
            return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, default=str)}], "isError": False}
        except api.ApiError as e:
            return {"content": [{"type": "text", "text": json.dumps({"error": str(e)}, ensure_ascii=False)}], "isError": True}
        except Exception:  # noqa: BLE001 — jamais de trace (chemins, secrets) vers le client
            log.exception("erreur interne dans %s", name)
            return {"content": [{"type": "text", "text": json.dumps({"error": "erreur interne"})}], "isError": True}


# ------------------------------------------------------------------ skills et agents

def skills_index(root):
    out = []
    base = os.path.join(root, "skills")
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        p = os.path.join(base, name, "SKILL.md")
        if SKILL_NAME.match(name) and os.path.isfile(p) and not os.path.islink(p):
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
            m = re.match(r"---\n(.*?)\n---\n", text, re.S)
            desc = ""
            if m:
                d = re.search(r"^description:\s*(.+)$", m.group(1), re.M)
                desc = d.group(1).strip() if d else ""
            out.append({"name": name, "description": desc})
    return out


def get_skill(root, name):
    if not SKILL_NAME.match(name or ""):
        raise api.ApiError("nom de skill invalide")
    p = os.path.join(root, "skills", name, "SKILL.md")
    if not os.path.isfile(p) or os.path.islink(p):
        raise api.ApiError("skill inconnu : " + ", ".join(s["name"] for s in skills_index(root)))
    with open(p, encoding="utf-8") as fh:
        text = fh.read()
    note = ("\n\n---\nNote d'exécution (client mobile/distant) : les commandes `python3 scripts/...` de ce skill n'existent pas sur ton "
            "appareil ; utilise les OUTILS de ce serveur (calcul, garde-fous, gabarits, glycémie, poids, ingestion, fichiers) qui "
            "font la même chose. Lis les données dans Open Wearables / Nightscout via leurs connecteurs.")
    return {"name": name, "instructions": text + note}


# ------------------------------------------------------------------ outils de calcul (pures, sans accès disque sauf profil)

def _profile(root):
    return arc_cycling.read_profile(os.path.join(root, coach_config.get(coach_config.load(root), "athlete.profile",
                                                                          "planning/Athlete_Profile.md")))


def build_registry(root):
    R = Registry(root)
    droot = lambda: api.data_root(root)  # noqa: E731

    # --- instructions
    R.tool("list_skills", "Liste les skills (procédures) du coach avec leur description. À appeler en premier.", S(),
           lambda: {"skills": skills_index(root)})
    R.tool("get_skill", "Texte complet d'un skill (ex. loop-overrides, openwearables-sync, garmin-workout-scheduling, today, week, log, "
           "nightscout-glucose, daily-sync, coach-setup). Suis-le en remplaçant les scripts par les outils de ce serveur.",
           S({"name": STR}, ["name"]), lambda name: get_skill(root, name))
    R.tool("get_instructions", "Prompt d'un coach (coach-route, coach-cx, coach-poids, medical, nutritionist), `contract` (format "
           "OBLIGATOIRE des fichiers), ou rien pour la liste et les règles du workspace.",
           S({"agent": STR}), lambda agent=None: api.get_instructions(root, agent))

    # --- état et fichiers
    R.tool("get_status", "État du jour : objectif, prochaine course, forme et charge, bilan matinal vs base personnelle, séances du jour "
           "et à venir, glycémie déjà enregistrée.", S(), lambda: api.status(root))
    R.tool("list_files", "Liste les fichiers d'un dossier : activities, medical, nutrition, planning, rapports ou resources.",
           S({"directory": STR}, ["directory"]), lambda directory: api.list_files(root, directory))
    R.tool("read_file", "Lit un fichier Markdown (ex. planning/Semaine_2026-10-12.md). Il s'ouvre par un bloc ```arc de JSON.",
           S({"path": STR}, ["path"]), lambda path: api.read_file(root, path))
    R.tool("write_file", "Écrit un fichier Markdown COMPLET (activities, medical, nutrition, planning, rapports). Titre « # … » puis bloc "
           "```arc valide (voir get_instructions('contract')). Un contenu invalide n'est PAS écrit. Chaque écriture est commitée.",
           S({"path": STR, "content": {"type": "string", "maxLength": api.MAX_BYTES}, "message": STR}, ["path", "content"]),
           lambda path, content, message="mise à jour": api.write_file(root, path, content, message), write=True)
    R.tool("update_session", "Modifie UNE séance d'une semaine planifiée (title, duration_s, intensity, key, planned_load, note, date, "
           "alt_date, status planned|done|missed|moved|cancelled). Pour annuler : status=cancelled. Rien n'est supprimé.",
           S({"week_start": STR, "date": STR, "changes": {"type": "object"}, "title_contains": STR}, ["week_start", "date", "changes"]),
           lambda week_start, date, changes, title_contains=None: api.update_session(root, week_start, date, changes, title_contains),
           write=True)
    R.tool("set_profile", "Met à jour le profil : ftp_w, lthr_bpm, hr_max_bpm, hr_rest_bpm, weight_kg, target_weight_kg, height_cm, "
           "body_fat_pct, birth_year, sex (m|f), available_days (liste mon..sun). Les verrous médicaux ne sont pas modifiables ici.",
           S({"key": STR, "value": {}}, ["key", "value"]), lambda key, value: api.set_profile(root, key, value), write=True)
    R.tool("history", "Derniers changements (git), globalement ou pour un fichier.",
           S({"path": STR, "n": INT}), lambda path=None, n=15: api.history(root, path, n))
    R.tool("undo_last_change", "Annule le dernier changement SI et seulement s'il vient de cette API (commit « [mobile] »).",
           S(), lambda: api.undo_last_change(root), write=True)
    R.tool("validate_contract", "Vérifie un contenu Markdown (titre + bloc ```arc) SANS l'écrire ; renvoie la liste d'erreurs.",
           S({"content": {"type": "string", "maxLength": api.MAX_BYTES}}, ["content"]), lambda content: _validate_text(content))

    # --- calculs déterministes
    R.tool("get_zones", "Zones de puissance (% FTP) et de FC (% seuil) calculées depuis le profil, avec W/kg.", S(),
           lambda: _zones(_profile(root)))
    R.tool("compute_session_load", "Charge d'une séance : puissance (np_w ou avg_power_w) > FC moyenne > RPE. Renvoie charge et méthode, "
           "ou rien si aucune méthode n'est possible (jamais 0).",
           S({"duration_s": NUM, "np_w": NUM, "avg_power_w": NUM, "avg_hr_bpm": NUM, "rpe": NUM}, ["duration_s"]),
           lambda duration_s, np_w=None, avg_power_w=None, avg_hr_bpm=None, rpe=None: dict(zip(
               ("load", "load_method"), arc_cycling.session_load(duration_s, _profile(root), np_w, avg_power_w, avg_hr_bpm, rpe))))
    R.tool("check_guardrails", "Passe les garde-fous R1…R7 sur une semaine planifiée (week_start = lundi AAAA-MM-JJ).",
           S({"week_start": STR}, ["week_start"]), lambda week_start: api.check_guardrails(root, week_start))
    R.tool("build_workout", "Construit le DTO Garmin d'une séance vélo depuis un gabarit (endurance, recovery, sweet_spot, threshold, vo2max, "
           "cx_race_sim, cx_starts, cx_opener) avec cibles de puissance du profil (FTP), sinon FC (LTHR), sinon sans cible.",
           S({"template": {"type": "string", "enum": arc_workout.TEMPLATES}, "duration_s": INT}, ["template", "duration_s"]),
           lambda template, duration_s: _workout(root, template, duration_s))
    R.tool("glucose_precheck", "Contrôle glycémique avant une séance (catégorie, glucides avant, rappels). Ne propose AUCUNE dose.",
           S({"mgdl": NUM, "direction": STR, "intensity": STR, "duration_s": NUM}, ["mgdl"]),
           lambda mgdl, direction=None, intensity="endurance", duration_s=3600: arc_glucose.precheck(
               mgdl, direction, intensity, duration_s, coach_config.load(root).get("glucose", {})))
    R.tool("glucose_session", "Analyse la glycémie autour d'une séance : glucose = liste {glucose_mgdl, direction, timestamp} "
           "(Nightscout, de start−15 min à end+2 h), treatments optionnels. Renvoie départ, min, max, hypo, flags.",
           S({"start": STR, "end": STR, "glucose": OBJ_LIST(800), "treatments": OBJ_LIST(400)}, ["start", "end", "glucose"]),
           lambda start, end, glucose, treatments=None: arc_glucose.session(
               {"result": glucose}, start, end, {"result": treatments} if treatments is not None else None,
               coach_config.load(root).get("glucose", {}).get("low_mgdl", 70)))
    R.tool("weight_plan", "Plan de perte de poids : rythme, déficit moyen, garde-fous (≤ 1 %/sem), verrou médical.",
           S({"weight_kg": NUM, "target_kg": NUM, "weeks": NUM}, ["weight_kg", "target_kg", "weeks"]),
           lambda weight_kg, target_kg, weeks: arc_weight.plan(weight_kg, target_kg, weeks, coach_config.load(root)))
    R.tool("fueling", "Glucides et boisson à prendre pendant une sortie (repères de consensus, pas des doses d'insuline).",
           S({"duration_s": NUM, "intensity": STR, "weight_kg": NUM}, ["duration_s"]),
           lambda duration_s, intensity="endurance", weight_kg=None: arc_weight.fueling(duration_s, intensity, weight_kg))

    # --- ingestion (les données sont lues par Claude dans Open Wearables, puis passées ici de façon COMPACTE)
    wk_keys = ("id", "type", "start_datetime", "end_datetime", "duration_seconds", "distance_meters", "calories_kcal",
               "avg_heart_rate_bpm", "max_heart_rate_bpm", "elevation_gain_meters", "source")
    R.tool("ingest_activities", "Enregistre des séances (activities/) depuis la réponse de get_workout_events d'Open Wearables (records) et, si "
           "disponible, la puissance minute par minute de get_timeseries(types=['power'], resolution='1min') (records). Charge calculée "
           "(puissance > FC), doublons fusionnés, jamais d'écrasement. Utilise dry_run=true d'abord. Garde les fenêtres COURTES (quelques jours).",
           S({"workouts": OBJ_LIST(120), "power": OBJ_LIST(4000), "since": STR, "dry_run": BOOL}, ["workouts"]),
           lambda workouts, power=None, since=None, dry_run=False: _ingest(
               root, "activities", [{k: w.get(k) for k in wk_keys} for w in workouts], power, since, dry_run), write=True)
    R.tool("ingest_health", "Enregistre des bilans santé (medical/) depuis get_timeseries (records : repos, HRV rmssd, poids, respiration, SpO₂) "
           "et get_sleep_summary (sleep). Aucun verdict n'est écrit. Utilise dry_run=true d'abord.",
           S({"daily": OBJ_LIST(5000), "sleep": OBJ_LIST(400), "since": STR, "dry_run": BOOL}),
           lambda daily=None, sleep=None, since=None, dry_run=False: _ingest(root, "health", daily, sleep, since, dry_run), write=True)
    return R


def _validate_text(content):
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        errs = arc_contract.validate_file(tmp)
    finally:
        os.unlink(tmp)
    return {"ok": not errs, "errors": errs}


def _zones(prof):
    out = {}
    if prof.get("ftp_w"):
        out["power"] = arc_cycling.power_zones(prof["ftp_w"])
        if prof.get("weight_kg"):
            out["w_per_kg"] = round(prof["ftp_w"] / prof["weight_kg"], 2)
    if prof.get("lthr_bpm"):
        out["hr"] = arc_cycling.hr_zones(prof["lthr_bpm"])
    return out or {"error": "ni ftp_w ni lthr_bpm au profil : à demander, jamais à inventer"}


def _workout(root, template, duration_s):
    prof = _profile(root)
    ftp, lthr = prof.get("ftp_w"), prof.get("lthr_bpm")
    spec = arc_workout.template(template, int(duration_s), ftp, lthr)
    dto = arc_workout.build(spec)
    return {"workout_data": dto, "targets_from": "power" if ftp else "hr" if lthr else "none",
            "duration_s": arc_workout.total_seconds(spec["steps"]), "validation_errors": arc_workout.validate(dto)}


def _ingest(root, kind, a, b, since, dry_run):
    droot = api.data_root(root)
    if kind == "activities":
        rep = arc_sync.sync_activities({"records": a}, {"records": b} if b else None, root, since, dry_run)
        paths = [f"activities/{w['file']}" for w in rep["written"]]
    else:
        rep = arc_sync.sync_health({"records": a} if a else None, {"records": b} if b else None, root, since, dry_run)
        paths = [f"medical/{d}_health.md" for d in rep["written"]]
    if not dry_run and paths:
        rep["commit"] = api.commit_paths(droot, paths, f"synchro {kind} ({len(paths)} fichier(s))")
    return rep


# ------------------------------------------------------------------ protocole JSON-RPC

def handle_rpc(msg, reg):
    """Retourne la réponse JSON-RPC (dict) ou None pour une notification/réponse."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "requête JSON-RPC 2.0 invalide"}}
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method is None:                       # réponse d'un client : rien à faire
        return None
    is_notification = "id" not in msg
    try:
        if method == "initialize":
            asked = params.get("protocolVersion")
            res = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                   "capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False}},
                   "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}
        elif method == "ping":
            res = {}
        elif method.startswith("notifications/"):
            return None
        elif method == "tools/list":
            res = {"tools": reg.listing()}
        elif method == "tools/call":
            if not isinstance(params.get("name"), str):
                raise RpcError(-32602, "name obligatoire")
            res = reg.call(params["name"], params.get("arguments"))
        elif method == "prompts/list":
            res = {"prompts": [{"name": s["name"], "description": s["description"], "arguments": []} for s in skills_index(reg.root)]}
        elif method == "prompts/get":
            try:
                sk = get_skill(reg.root, params.get("name"))
            except api.ApiError as e:
                raise RpcError(-32602, str(e))
            res = {"description": sk["name"], "messages": [{"role": "user", "content": {"type": "text", "text": sk["instructions"]}}]}
        else:
            raise RpcError(-32601, f"méthode inconnue : {method}")
    except RpcError as e:
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": e.code, "message": e.message}}
    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": mid, "result": res}


# ------------------------------------------------------------------ HTTP

def make_handler(reg, token, allowed_hosts):
    if len(token or "") < 24:
        raise SystemExit("COACH_MCP_TOKEN absent ou trop court (24 caractères minimum) : refus de démarrer")
    tok = token.encode()

    class H(http.server.BaseHTTPRequestHandler):
        server_version = "arc-mcp"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body=b"", ctype="application/json", extra=None):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if code >= 400:
                # Refus avant lecture du corps : on FERME la connexion, sinon le corps non lu serait pris pour la requête suivante
                # par un proxy qui réutilise la connexion (réponse 501 erronée constatée derrière Traefik).
                self.close_connection = True
                self.send_header("Connection", "close")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if data:
                self.wfile.write(data)

        def _guard(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if host not in allowed_hosts:
                self._send(403, json.dumps({"error": "hôte refusé"}))
                return False
            if self.headers.get("Origin"):                       # un client MCP serveur-à-serveur n'envoie pas d'Origin
                self._send(403, json.dumps({"error": "origine refusée"}))
                return False
            return True

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/health":
                return self._send(200, json.dumps({"ok": True}))
            self._send(405, json.dumps({"error": "POST uniquement (pas de flux SSE)"}), extra={"Allow": "POST"})

        def do_POST(self):  # noqa: N802
            if self.path.split("?", 1)[0] != "/mcp":
                return self._send(404, json.dumps({"error": "Not Found"}))
            if not self._guard():
                return
            supplied = self.headers.get("X-Api-Key") or (self.headers.get("Authorization") or "").removeprefix("Bearer ")
            if not supplied or not hmac.compare_digest(supplied.encode(), tok):
                return self._send(401, json.dumps({"error": "Unauthorized"}), extra={"WWW-Authenticate": "Bearer"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n <= 0 or n > MAX_BODY:
                return self._send(413 if n > MAX_BODY else 400, json.dumps({"error": "corps invalide ou trop grand"}))
            try:
                msg = json.loads(self.rfile.read(n).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._send(200, json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON invalide"}}))
            batch = isinstance(msg, list)
            out = [r for r in (handle_rpc(m, reg) for m in (msg if batch else [msg])) if r is not None]
            if not out:
                return self._send(202)
            self._send(200, json.dumps(out if batch else out[0], ensure_ascii=False))

        def do_DELETE(self):  # noqa: N802
            self._send(405, json.dumps({"error": "pas de session"}), extra={"Allow": "POST"})

        do_PUT = do_PATCH = do_DELETE  # noqa: N815

    return H
