#!/usr/bin/env python3
"""API de fichiers du coach — logique pure (stdlib), enveloppée en MCP par `deploy/freebox/mcp_app.py`.

But : depuis Claude mobile, lire et modifier les fichiers que lit le tableau de bord (séances, plan, santé, profil),
sans jamais pouvoir toucher autre chose. Chaque écriture est VALIDÉE (contrat `arc`) avant d'exister, ATOMIQUE, et
COMMITÉE dans git (annulable). Rien n'est supprimé.

Garde-fous (tous testés) :
- lecture : activities/ medical/ nutrition/ planning/ rapports/ resources/ ; écriture : sans resources/ ;
- noms de fichiers `[A-Za-z0-9_.-]+.md`, un seul niveau de dossier (+ planning/archive en lecture), ni `..`, ni chemin
  absolu, ni lien symbolique, ni sortie de la racine des données ; taille ≤ 200 Ko ;
- jamais `config/` (verrou médical, identifiants), jamais de script ni de secret ;
- un fichier qui ne passe pas `arc_contract` n'est PAS écrit ;
- `undo_last_change` n'annule qu'un commit fait par cette API (préfixe `[mobile]`).

La racine du code (`root`, scripts/agents) et celle des données (`data_root`, dépôt git) peuvent différer (conteneur) ;
par défaut elles sont identiques.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arc_contract  # noqa: E402
import arc_guardrails  # noqa: E402
import coach_config  # noqa: E402

READ_DIRS = ("activities", "medical", "nutrition", "planning", "rapports", "resources")
WRITE_DIRS = ("activities", "medical", "nutrition", "planning", "rapports")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.md$")
MAX_BYTES = 200_000
COMMIT_PREFIX = "[mobile]"
AUTHOR = "Claude mobile <mobile@coach.local>"
AGENTS = ("coach-route", "coach-cx", "coach-poids", "medical", "nutritionist")

SESSION_FIELDS = {"title": str, "duration_s": (int, float), "intensity": str, "key": bool, "planned_load": (int, float),
                  "note": str, "date": str, "status": str, "alt_date": str}
STATUSES = {"planned", "done", "missed", "moved", "cancelled"}
PROFILE_KEYS = {  # clé : (type, min, max)
    "ftp_w": (float, 50, 600), "lthr_bpm": (float, 100, 220), "hr_max_bpm": (float, 120, 230),
    "hr_rest_bpm": (float, 30, 100), "weight_kg": (float, 30, 250), "target_weight_kg": (float, 30, 250),
    "height_cm": (float, 120, 230), "body_fat_pct": (float, 3, 60), "birth_year": (int, 1930, 2020),
}
DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


class ApiError(Exception):
    pass


def data_root(root):
    return os.environ.get("ARC_DATA_ROOT") or root


def _resolve(droot, rel, write=False):
    if not isinstance(rel, str) or not rel or "\x00" in rel or "\\" in rel or rel.startswith("/"):
        raise ApiError("chemin invalide")
    parts = rel.split("/")
    allowed = WRITE_DIRS if write else READ_DIRS
    if parts[0] not in allowed:
        raise ApiError(f"dossier non autorisé « {parts[0]} » (autorisés : {', '.join(allowed)})")
    if len(parts) == 3 and parts[0] == "planning" and parts[1] == "archive" and not write:
        pass
    elif len(parts) != 2:
        raise ApiError("un seul niveau de dossier est accepté")
    if any(p in ("", ".", "..") for p in parts) or not NAME.match(parts[-1]):
        raise ApiError("nom de fichier invalide (lettres, chiffres, _ . - et extension .md)")
    base = os.path.realpath(os.path.join(droot, parts[0]))
    path = os.path.join(base, *parts[1:])
    if os.path.islink(path) or os.path.commonpath([base, os.path.realpath(os.path.dirname(path))]) != base:
        raise ApiError("chemin hors de la zone autorisée")
    return path


def _git(droot, *args, check=True):
    env = dict(os.environ, GIT_AUTHOR_NAME="Claude mobile", GIT_AUTHOR_EMAIL="mobile@coach.local",
               GIT_COMMITTER_NAME="Claude mobile", GIT_COMMITTER_EMAIL="mobile@coach.local")
    r = subprocess.run(["git", "-C", droot, *args], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise ApiError(f"git : {r.stderr.strip() or r.stdout.strip()}")
    return r


def _is_repo(droot):
    return os.path.isdir(os.path.join(droot, ".git"))


def _commit(droot, rel, message):
    if not _is_repo(droot):
        return None
    _git(droot, "add", "--", rel)
    if _git(droot, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None  # rien n'a changé
    _git(droot, "commit", "-q", "-m", f"{COMMIT_PREFIX} {message}"[:200])
    return _git(droot, "rev-parse", "--short", "HEAD").stdout.strip()


# ------------------------------------------------------------------ lecture

def list_files(root, directory):
    droot = data_root(root)
    if directory not in READ_DIRS:
        raise ApiError(f"dossier non autorisé (autorisés : {', '.join(READ_DIRS)})")
    base = os.path.join(droot, directory)
    out = []
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        p = os.path.join(base, name)
        if NAME.match(name) and os.path.isfile(p) and not os.path.islink(p):
            st = os.stat(p)
            out.append({"path": f"{directory}/{name}", "bytes": st.st_size,
                        "modified": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
    return {"directory": directory, "files": out}


def read_file(root, rel):
    path = _resolve(data_root(root), rel)
    if not os.path.isfile(path):
        raise ApiError("fichier introuvable")
    if os.path.getsize(path) > MAX_BYTES:
        raise ApiError("fichier trop volumineux")
    with open(path, encoding="utf-8") as fh:
        return {"path": rel, "content": fh.read()}


# ------------------------------------------------------------------ écriture (validée, atomique, commitée)

def write_file(root, rel, content, message="mise à jour"):
    droot = data_root(root)
    path = _resolve(droot, rel, write=True)
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_BYTES:
        raise ApiError(f"contenu invalide ou supérieur à {MAX_BYTES} octets")
    os.makedirs(os.path.dirname(path), exist_ok=True)       # dossier de la liste blanche : peut ne pas exister encore
    fd, tmp = tempfile.mkstemp(prefix=".arc-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        if not content.lstrip().startswith("#"):
            return {"ok": False, "errors": ["le fichier doit commencer par un titre « # … »"]}
        errs = arc_contract.validate_file(tmp)
        if errs:
            return {"ok": False, "errors": errs, "written": False}
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    return {"ok": True, "path": rel, "commit": _commit(droot, rel, f"{rel} : {message}")}


def _arc_span(text):
    m = arc_contract.BLOCK.search(text)
    if not m:
        raise ApiError("aucun bloc arc dans le fichier")
    return m, json.loads(m.group(1))


def _rewrite_block(text, obj):
    m, _ = _arc_span(text)
    return text[:m.start(1)] + json.dumps(obj, ensure_ascii=False, indent=1) + text[m.end(1):]


def update_session(root, week_start, date, changes, title_contains=None):
    """Modifie UNE séance d'une semaine (déplacer, durée, intensité, statut, note…)."""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(week_start)):
        raise ApiError("week_start : AAAA-MM-JJ (un lundi)")
    rel = f"planning/Semaine_{week_start}.md"
    path = _resolve(data_root(root), rel, write=True)
    if not os.path.isfile(path):
        raise ApiError(f"semaine introuvable : {rel}")
    bad = [k for k in changes if k not in SESSION_FIELDS]
    if bad:
        raise ApiError(f"champs non modifiables : {bad} (autorisés : {sorted(SESSION_FIELDS)})")
    for k, v in changes.items():
        if isinstance(v, bool) != (SESSION_FIELDS[k] is bool) or not isinstance(v, SESSION_FIELDS[k]):
            raise ApiError(f"{k} : type invalide")
    if "status" in changes and changes["status"] not in STATUSES:
        raise ApiError(f"status : {sorted(STATUSES)}")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    _, obj = _arc_span(text)
    hits = [s for s in obj.get("sessions", []) if s.get("date") == date
            and (not title_contains or title_contains.lower() in s.get("title", "").lower())]
    if not hits:
        raise ApiError("aucune séance à cette date" + (" avec ce titre" if title_contains else ""))
    if len(hits) > 1:
        raise ApiError("plusieurs séances ce jour-là : précise title_contains (" +
                       " | ".join(s.get("title", "?") for s in hits) + ")")
    s = hits[0]
    before = {k: s.get(k) for k in changes}
    s.update(changes)
    s.setdefault("changed_from_mobile", True)
    res = write_file(root, rel, _rewrite_block(text, obj), f"séance {date} {sorted(changes)}")
    res["before"], res["after"] = before, {k: s[k] for k in changes}
    return res


def set_profile(root, key, value):
    rel = coach_config.get(coach_config.load(root), "athlete.profile", "planning/Athlete_Profile.md")
    if key == "available_days":
        if not isinstance(value, list) or not value or not set(value) <= DAYS:
            raise ApiError(f"available_days : liste non vide parmi {sorted(DAYS)}")
    elif key == "sex":
        if value not in ("m", "f"):
            raise ApiError("sex : m ou f")
    elif key in PROFILE_KEYS:
        typ, lo, hi = PROFILE_KEYS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
            raise ApiError(f"{key} : nombre entre {lo} et {hi}")
        value = int(value) if typ is int else value
    else:
        raise ApiError(f"clé non modifiable : {key} (autorisées : {sorted(list(PROFILE_KEYS) + ['sex', 'available_days'])})")
    path = _resolve(data_root(root), rel, write=True)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    _, obj = _arc_span(text)
    before = obj.get(key)
    obj[key] = value
    res = write_file(root, rel, _rewrite_block(text, obj), f"profil {key}")
    res["before"], res["after"] = before, value
    return res


# ------------------------------------------------------------------ calculs (lecture seule)

def check_guardrails(root, week_start):
    rel = f"planning/Semaine_{week_start}.md"
    path = _resolve(data_root(root), rel)
    with open(path, encoding="utf-8") as fh:
        _, obj = _arc_span(fh.read())
    return arc_guardrails.check(obj, root, dt.date.today())


def status(root):
    import arc_serve
    return {"summary": arc_serve.api_summary(root), "today": arc_serve.api_today(root)}


# ------------------------------------------------------------------ historique

def history(root, path=None, n=15):
    droot = data_root(root)
    if not _is_repo(droot):
        return {"commits": [], "note": "dossier de données non versionné"}
    args = ["log", f"-{min(max(int(n), 1), 50)}", "--format=%h|%ad|%s", "--date=format:%Y-%m-%d %H:%M"]
    if path:
        _resolve(droot, path)
        args += ["--", path]
    rows = [l.split("|", 2) for l in _git(droot, *args).stdout.splitlines() if l]
    return {"commits": [{"commit": a, "date": b, "message": c} for a, b, c in rows]}


def undo_last_change(root):
    droot = data_root(root)
    if not _is_repo(droot):
        raise ApiError("dossier de données non versionné")
    msg = _git(droot, "log", "-1", "--format=%s").stdout.strip()
    if not msg.startswith(COMMIT_PREFIX):
        raise ApiError("le dernier commit ne vient pas de cette API : annulation refusée")
    _git(droot, "revert", "--no-edit", "HEAD")
    return {"ok": True, "reverted": msg}


def get_instructions(root, agent=None):
    """Instructions des coachs (agents/*.md) pour que Claude mobile agisse comme eux. Lues dans le CODE, jamais les données."""
    def rd(p):
        with open(os.path.join(root, p), encoding="utf-8") as fh:
            return fh.read()
    if agent is None:
        return {"agents": list(AGENTS) + ["contract"], "workspace": rd("AGENTS.md")}
    if agent == "contract":
        return {"agent": "contract", "instructions": rd("skills/workspace-data-contract/SKILL.md")}
    if agent not in AGENTS:
        raise ApiError(f"agent inconnu : {sorted(AGENTS) + ['contract']}")
    return {"agent": agent, "instructions": rd(f"agents/{agent}.md")}
