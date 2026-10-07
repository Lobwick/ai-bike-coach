# Image unique : site + API MCP + outils, bibliothèque standard seulement (aucun pip install : ~27 Mo de mémoire en marche).
# Contexte de build : la racine du dépôt. Aucune donnée personnelle dans l'image (voir .dockerignore) : elles arrivent par volumes.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY scripts/ scripts/
COPY web/ web/
COPY agents/ agents/
COPY skills/ skills/
COPY templates/ templates/
COPY AGENTS.md ./
COPY config/workspace.toml config/coaching-styles.md config/
COPY config/sports/ config/sports/

ENV HOME=/tmp PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ARC_ROOT=/app ARC_DATA_ROOT=/data
EXPOSE 8000 8001
CMD ["sh", "-c", "git config --global --add safe.directory /data && exec python3 scripts/arc_coach_server.py"]
