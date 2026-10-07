#!/usr/bin/env python3
"""Résolution de la configuration : config/workspace.toml + workspace.user.toml.

Les valeurs de `workspace.user.toml` priment, clé par clé. Une clé présente mais
vide gagne (c'est ainsi qu'on annule un héritage).

Python 3.9+ sans dépendance : `tomllib` (3.11+) si disponible, sinon un analyseur
du sous-ensemble TOML utilisé par le projet (tables, chaînes, nombres, booléens,
listes à plat, commentaires).

    python3 scripts/coach_config.py get data.source
    python3 scripts/coach_config.py dump
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _split_array(body):
    items, cur, quote = [], "", None
    for ch in body:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == ",":
            items.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        items.append(cur)
    return items


def _value(raw):
    raw = raw.strip()
    if raw.startswith("["):
        return [_value(x) for x in _split_array(raw[1:raw.rindex("]")]) if x.strip()]
    if raw[:1] in "\"'":
        q = raw[0]
        return raw[1:raw.index(q, 1)]
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw.replace("_", ""))
    except ValueError:
        return float(raw.replace("_", ""))


def _strip_comment(line):
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def parse_toml(text):
    try:
        import tomllib  # type: ignore
        return tomllib.loads(text)
    except ImportError:
        pass
    data, table = {}, None
    table = data
    for line in text.splitlines():
        line = _strip_comment(line).strip()
        if not line:
            continue
        m = re.match(r"^\[([A-Za-z0-9_.]+)\]$", line)
        if m:
            table = data
            for part in m.group(1).split("."):
                table = table.setdefault(part, {})
            continue
        if "=" in line:
            key, raw = line.split("=", 1)
            table[key.strip()] = _value(raw)
    return data


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load(root=ROOT):
    cfg = {}
    for name in ("workspace.toml", "workspace.user.toml"):
        path = os.path.join(root, "config", name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                _merge(cfg, parse_toml(fh.read()))
    return cfg


def get(cfg, dotted, default=None):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def main(argv):
    cfg = load()
    if len(argv) >= 3 and argv[1] == "get":
        val = get(cfg, argv[2])
        print(json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val)
        return 0 if val is not None else 1
    if len(argv) >= 2 and argv[1] == "dump":
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
