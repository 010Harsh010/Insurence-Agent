# ---------------------------------------------------------------------------
# Backend — Insurance Agent (Flask + Python 3.12)
#
# Build context: . (repo root) — set in docker-compose
#
# Dependency caching strategy (fast rebuilds):
#   Layer 1 — system deps       → cached unless apt packages change
#   Layer 2 — uv install        → cached unless uv version changes
#   Layer 3 — uv sync (deps)    → ONLY re-runs when pyproject.toml or uv.lock changes
#   Layer 4 — app code COPY     → runs on every code change (fast, no dep install)
#
# So after the first build, a pure code change (editing main.py, services/, etc.)
# rebuilds in seconds — the dep layer is fully cached by Docker.
# ---------------------------------------------------------------------------

FROM python:3.12-slim

WORKDIR /app

# ---------- Python hygiene ----------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# uv creates the venv at /app/.venv (workspace root = WORKDIR)
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

# ---------- System deps (cached) ----------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libxcb1 \
        libx11-6 \
        libxau6 \
        libxdmcp6 && \
    rm -rf /var/lib/apt/lists/*

# ---------- Install uv (cached) ----------
RUN pip install --no-cache-dir uv

# ---------- Dependency installation (cached unless lock/pyproject changes) ----------
# Copy only the files uv needs to resolve dependencies — NOT the app code yet.
# This layer is cached and skipped on pure code-only rebuilds.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml ./backend/

# --frozen  → respect uv.lock exactly (no resolution, reproducible builds)
# --package backend → install only the backend workspace member and its deps
RUN uv sync --frozen --package backend

# ---------- Application code (runs on every code change, but fast — no dep install) ----------
COPY backend/ ./backend/

WORKDIR /app/backend

EXPOSE 8000

CMD ["uv", "run", "python", "main.py"]