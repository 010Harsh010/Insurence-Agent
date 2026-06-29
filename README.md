# Plum AI Engineer Assignment

## Overview

This repository contains the full submission for Plum's health insurance claims processing assignment. It includes:

- a `frontend/` React application
- a `backend/` Flask API with a multi-agent claim adjudication pipeline
- Docker-based local infrastructure for PostgreSQL, Prometheus, and Grafana
- assignment inputs and supporting reference material

## Repository Structure

```text
.
|-- README.md
|-- EXAMPLES.md
|-- assignment.md
|-- sample_documents_guide.md
|-- backend/
|-- frontend/
|-- inputs/
|-- policy_terms.json
|-- pyproject.toml
|-- Docker-compose.yml
`-- uv.lock
```

## Setup

### Option 1: Run with Docker Compose

This is the easiest way to start the full stack.

```bash
docker compose up --build
```

After startup:

- frontend: `http://localhost`
- backend API: proxied through the frontend at `/api`
- postgres: `localhost:8800`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3001`

Notes:

- the backend container reads environment variables from `backend/.env`
- Docker overrides `DB_HOST=postgres` and `DB_PORT=5432` inside the container

### Option 2: Run the backend locally

Prerequisites:

- Python `3.12`
- `uv`
- PostgreSQL running locally

Install backend dependencies from the repo root:

```bash
uv sync --package backend
```

Then start the backend:

```bash
cd backend
python main.py
```

The backend starts on port `8000`.

Before running locally, make sure `backend/.env` is configured with at least:

- `GROQ_API_KEY`
- `DB_HOST`
- `DB_PORT`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `ADMIN_PASSWORD`

### Option 3: Run the frontend locally

If you want the frontend outside Docker, use the standard Vite flow from `frontend/`.

Typical commands:

```bash
cd frontend
npm install
npm run dev
```

If you run the frontend locally, point it at the backend URL you are using.

## Recommended Reading Order

1. Read `assignment.md` to understand the problem statement and expected scope.
2. Read this `README.md` for repository-level setup and navigation.
3. Read `EXAMPLES.md` to see sample queries, outputs, and known behavior gaps.
4. Read the backend documentation listed below depending on what you are trying to do.

## Backend Documentation Guide

The main backend documentation files serve different purposes:

| File | Use |
|---|---|
| [`backend/README.md`](backend/README.md) | Start here for the backend. It explains the API, stack, folder structure, environment variables, local development flow, Docker flow, endpoints, and the overall claim-processing lifecycle. |
| [`backend/sub_agent/README.md`](backend/sub_agent/README.md) | Use this when you need the detailed logic of the claim pipeline in `policyAgent.py`. It breaks down each validation agent, decision rules, database writes, and common claim scenarios step by step. |
| [`backend/ARCHITECTURE.md`](backend/ARCHITECTURE.md) | Use this for system design and visual flow documentation. It contains sequence diagrams for claim processing, uploads, text-to-SQL, decisioning, database interactions, auth, and error handling. |

## Other Important Files

| File | Use |
|---|---|
| `EXAMPLES.md` | Example queries, sample outputs, screenshots, and known issues observed during testing. |
| `assignment.md` | Original assignment brief and requirements. |
| `sample_documents_guide.md` | Reference for medical document types and extraction expectations. |
| `policy_terms.json` | Policy configuration and rules used by the backend logic. |
| `backend/test_cases.json` | Backend claim test scenarios and expected outcomes. |

## Quick Navigation

- Building or running the app: start with this `README.md`
- Reviewing sample behavior and edge cases: read `EXAMPLES.md`
- Understanding backend behavior: read `backend/README.md`
- Understanding claim adjudication logic in depth: read `backend/sub_agent/README.md`
- Understanding end-to-end architecture and flows: read `backend/ARCHITECTURE.md`
