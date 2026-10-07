#!/usr/bin/env python3
"""Un seul processus : le SITE (lecture seule, derrière un proxy authentifiant) et l'API MCP (jeton), sur deux ports distincts.

    COACH_MCP_TOKEN=… ARC_LISTEN=0.0.0.0 ARC_ALLOWED_HOSTS=hote.example ARC_PROXY_AUTH=1 python3 scripts/arc_coach_server.py

Deux ports pour deux niveaux d'authentification (le proxy route /coach → site avec mot de passe, /mcp-coach → MCP avec jeton) :
le port du site ne sert JAMAIS /mcp, le port MCP ne sert JAMAIS les pages ni l'API du site. Bibliothèque standard seulement
(≈ 30 Mo), conçu pour une machine à mémoire comptée.
"""
import logging
import os
import socketserver
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arc_mcp  # noqa: E402
import arc_serve  # noqa: E402

ROOT = os.environ.get("ARC_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bind(handler, host, port):
    srv = socketserver.ThreadingTCPServer((host, port), handler)
    srv.daemon_threads = True
    srv.allow_reuse_address = True
    return srv


def build(root=ROOT, site_port=8000, mcp_port=8001, token=None):
    host = arc_serve.listen_address()                      # refuse hors boucle locale sans hôtes autorisés + proxy authentifiant
    token = token or os.environ.get("COACH_MCP_TOKEN", "")
    reg = arc_mcp.build_registry(root)
    mcp_handler = arc_mcp.make_handler(reg, token, arc_serve.allowed_hosts())      # refuse de démarrer sans jeton
    return (bind(arc_serve.make_handler(root), host, site_port), bind(mcp_handler, host, mcp_port))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    site, mcp = build(site_port=int(os.environ.get("ARC_SITE_PORT", 8000)), mcp_port=int(os.environ.get("ARC_MCP_PORT", 8001)))
    threading.Thread(target=mcp.serve_forever, daemon=True).start()
    print(f"site : http://{site.server_address[0]}:{site.server_address[1]}/  ·  MCP : http://{mcp.server_address[0]}:{mcp.server_address[1]}/mcp", flush=True)
    try:
        site.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
