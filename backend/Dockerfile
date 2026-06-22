FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV UV_HTTP_TIMEOUT=600

ENV PATH="/app/.venv/bin:$PATH"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./

COPY backend/pyproject.toml ./backend/pyproject.toml

RUN uv sync --frozen --no-dev --package backend

COPY backend ./backend

COPY policy_terms.json ./backend/policy_terms.json

WORKDIR /app/backend

EXPOSE 8000

CMD ["uv", "run", "main.py"]