# Image unique pour le site (arc_serve.py) et l'API MCP (mcp_app.py). Contexte de build : la racine du dépôt.
# Aucune donnée personnelle dans l'image (voir .dockerignore) : elles arrivent par volumes.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "fastmcp>=3.0.0,<4" "uvicorn>=0.30"

WORKDIR /app
COPY scripts/ scripts/
COPY web/ web/
COPY agents/ agents/
COPY templates/ templates/
COPY skills/workspace-data-contract/ skills/workspace-data-contract/
COPY AGENTS.md ./
COPY config/workspace.toml config/coaching-styles.md config/
COPY config/sports/ config/sports/
COPY deploy/freebox/mcp_app.py mcp_app.py

ENV HOME=/tmp PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
