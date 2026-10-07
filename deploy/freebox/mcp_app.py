"""API MCP du coach — lit et modifie les fichiers que lit le tableau de bord (Claude mobile, claude.ai).

Toute la logique et ses garde-fous sont dans `scripts/arc_files_api.py` (testée) ; ce fichier ne fait que l'exposer en MCP,
derrière un jeton OBLIGATOIRE (le serveur refuse de démarrer sans lui — contrairement à un serveur « ouvert si pas de jeton »).

Lancement : uvicorn mcp_app:app --host 0.0.0.0 --port 8000   (derrière Traefik, route /mcp-coach → /mcp)
"""
import hmac
import logging
import os
import sys
import threading
import time
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

from fastmcp import FastMCP  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

import arc_files_api as api  # noqa: E402

log = logging.getLogger("coach-mcp")
ROOT = os.environ.get("ARC_ROOT", os.path.dirname(os.path.abspath(__file__)))
TOKEN = os.environ.get("COACH_MCP_TOKEN", "")
if len(TOKEN) < 24:
    raise SystemExit("COACH_MCP_TOKEN absent ou trop court (24 caractères minimum) : refus de démarrer")
MAX_BODY = 400_000
WRITES_PER_5MIN = 30

mcp = FastMCP(name="ai-bike-coach")
_writes, _lock = deque(), threading.Lock()


def _rate_limit_writes():
    now = time.time()
    with _lock:
        while _writes and now - _writes[0] > 300:
            _writes.popleft()
        if len(_writes) >= WRITES_PER_5MIN:
            raise api.ApiError(f"trop d'écritures ({WRITES_PER_5MIN} / 5 min) : réessaie plus tard")
        _writes.append(now)


def _run(fn, *args, write=False, **kwargs):
    try:
        if write:
            _rate_limit_writes()
        out = fn(ROOT, *args, **kwargs)
        if write:
            log.info("écriture %s %s", fn.__name__, args[:2])
        return out
    except api.ApiError as e:
        return {"error": str(e)}
    except Exception:  # noqa: BLE001 — ne jamais renvoyer de trace (chemins, secrets) au client
        log.exception("erreur interne dans %s", fn.__name__)
        return {"error": "erreur interne"}


@mcp.tool
def get_instructions(agent: str | None = None) -> dict:
    """Instructions du coach. Sans argument : liste des coachs et règles du workspace.
    Avec `agent` = coach-route | coach-cx | coach-poids | medical | nutritionist : son prompt complet.
    Avec `agent` = contract : le CONTRAT DE DONNÉES (format obligatoire des fichiers).

    Notes for LLMs : appelle `get_instructions("contract")` avant toute écriture ; adopte le coach adapté à la demande ;
    la lecture des données se fait via Open Wearables et Nightscout (connecteurs séparés), jamais via cet outil.
    """
    return _run(api.get_instructions, agent)


@mcp.tool
def get_status() -> dict:
    """État du jour : objectif, prochaine course, forme et charge, bilan matinal, séances du jour et à venir, glycémie déjà enregistrée."""
    return _run(api.status)


@mcp.tool
def list_files(directory: str) -> dict:
    """Liste les fichiers d'un dossier : activities, medical, nutrition, planning, rapports ou resources."""
    return _run(api.list_files, directory)


@mcp.tool
def read_file(path: str) -> dict:
    """Lit un fichier Markdown, ex. `planning/Semaine_2026-10-12.md` ou `planning/Athlete_Profile.md`.
    Il s'ouvre par un bloc ```arc de JSON, suivi du texte libre."""
    return _run(api.read_file, path)


@mcp.tool
def write_file(path: str, content: str, message: str = "mise à jour") -> dict:
    """Écrit un fichier Markdown COMPLET (activities, medical, nutrition, planning, rapports). Le contenu doit s'ouvrir par un
    titre « # … » puis un bloc ```arc valide (voir `get_instructions("contract")`). Un contenu invalide n'est PAS écrit : la
    réponse liste les erreurs, corrige-les et réessaie. Chaque écriture est commitée (annulable avec `undo_last_change`).
    Pour un simple changement de séance ou de profil, préfère `update_session` / `set_profile`."""
    return _run(api.write_file, path, content, message, write=True)


@mcp.tool
def update_session(week_start: str, date: str, changes: dict, title_contains: str | None = None) -> dict:
    """Modifie UNE séance d'une semaine planifiée. `week_start` = lundi AAAA-MM-JJ, `date` = jour de la séance.
    `changes` parmi : title, duration_s, intensity, key, planned_load, note, date (déplacer, dans la même semaine), alt_date,
    status (planned | done | missed | moved | cancelled). Plusieurs séances le même jour : précise `title_contains`.
    Pour annuler : changes={"status": "cancelled"}. Rien n'est supprimé."""
    return _run(api.update_session, week_start, date, changes, title_contains, write=True)


@mcp.tool
def set_profile(key: str, value: float | int | str | list[str]) -> dict:
    """Met à jour une valeur du profil athlète : ftp_w, lthr_bpm, hr_max_bpm, hr_rest_bpm, weight_kg, target_weight_kg,
    height_cm, body_fat_pct, birth_year, sex (m|f), available_days (liste mon..sun). Les verrous médicaux ne sont pas modifiables ici."""
    return _run(api.set_profile, key, value, write=True)


@mcp.tool
def check_guardrails(week_start: str) -> dict:
    """Passe les garde-fous (rampe de charge, jours durs, perte de poids, déficit, qualité après verdict rouge) sur une semaine."""
    return _run(api.check_guardrails, week_start)


@mcp.tool
def history(path: str | None = None, n: int = 15) -> dict:
    """Derniers changements (git), globalement ou pour un fichier."""
    return _run(api.history, path, n)


@mcp.tool
def undo_last_change() -> dict:
    """Annule le dernier changement SI et seulement s'il a été fait par cette API (commit « [mobile] »)."""
    return _run(api.undo_last_change, write=True)


class AuthMiddleware(BaseHTTPMiddleware):
    """Jeton obligatoire (en-tête X-Api-Key ou Authorization: Bearer), comparaison à temps constant. /health reste ouvert."""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path == "/health":
            return JSONResponse({"ok": True})
        if path != "/mcp":
            return JSONResponse({"error": "Not Found"}, status_code=404)
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            return JSONResponse({"error": "Payload too large"}, status_code=413)
        supplied = request.headers.get("x-api-key", "") or request.headers.get("authorization", "").removeprefix("Bearer ")
        if not supplied or not hmac.compare_digest(supplied.encode(), TOKEN.encode()):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


app = mcp.http_app(stateless_http=True)
app.add_middleware(AuthMiddleware)
