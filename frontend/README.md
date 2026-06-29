# Frontend

## Overview

This frontend is a React + Vite single-page application for the Plum claims processing system. It provides:

- a chat interface for claim-related conversations
- document upload for medical files
- claim decision rendering with financial breakdowns
- admin actions for claim updates, policy upload, document deletion, and database reset
- a test page for running and reviewing backend test results

## Tech Stack

| Category | Technology |
|---|---|
| Framework | React 19 |
| Build Tool | Vite 6 |
| Styling | Tailwind CSS 4 + custom CSS |
| Icons | lucide-react |
| Runtime | Node.js |
| Production Serving | nginx |

## Folder Structure

```text
frontend/
|-- src/
|   |-- App.jsx         # Main application UI and interaction logic
|   |-- main.jsx        # React entry point
|   |-- index.css       # Global styling
|   `-- assets/         # Static frontend assets
|-- Dockerfile          # Multi-stage frontend build
|-- nginx.conf          # Static hosting + /api reverse proxy
|-- package.json        # Scripts and dependencies
|-- vite.config.js      # Dev server config and API proxy rules
`-- README.md
```

## Features

- **Claims chat UI**: users can describe a claim, ask questions, and view assistant responses in a conversational layout.
- **Document upload flow**: supports PDF and image uploads (`.pdf`, `.png`, `.jpg`, `.jpeg`) tied to a member ID.
- **Decision cards**: displays claim outcomes such as `APPROVED`, `REJECTED`, `PARTIALLY_APPROVED`, and `MANUAL_REVIEW`.
- **Financial breakdown**: shows the claimed amount, deductions, and approved amount when the claim is not rejected.
- **Q&A results**: renders structured answer payloads from the backend as tables and key-value views.
- **Admin workflows**: supports protected claim updates and policy upload, plus document cleanup and DB reset actions.
- **Test runner page**: includes a UI for executing backend test cases and reviewing results.

## Setup

### Prerequisites

- Node.js
- npm
- backend running locally or through Docker

## Local Development

Install dependencies:

```bash
cd frontend
npm install
```

Start the Vite development server:

```bash
npm run dev
```

The frontend runs on:

- `http://localhost:5173`

## Development API Routing

In local development, Vite proxies these frontend requests to the backend target:

- `/chat`
- `/upload`
- `/health`
- `/updateClaim`
- `/resetDB`
- `/addPolicy`
- `/member`
- `/test`

By default, the proxy target is:

```text
http://127.0.0.1:8000
```

You can override it with:

```bash
VITE_API_PROXY_TARGET=http://your-backend-host:8000
```

## Production / Docker Behavior

The frontend Docker image uses a multi-stage build:

1. `node:22-alpine` installs dependencies and runs `vite build`
2. `nginx:alpine` serves the generated static files

In the Docker setup:

- nginx serves the SPA on port `80`
- requests to `/api/*` are proxied to `backend:8000`
- the `/api` prefix is stripped before forwarding

Examples:

- `/api/chat` -> backend `/chat`
- `/api/upload` -> backend `/upload`

To build the frontend alone:

```bash
cd frontend
npm run build
```

To preview the production build locally:

```bash
npm run preview
```

## Environment Notes

The app reads:

- `VITE_BACKEND_BASE`
- `VITE_API_PROXY_TARGET`

How they are used:

- `VITE_BACKEND_BASE` is used by the app at runtime to build request URLs.
- `VITE_API_PROXY_TARGET` is used by the Vite dev server proxy.

Current code behavior:

- if `VITE_BACKEND_BASE` is not set, the app falls back to `http://localhost:8000`
- in Docker, the nginx layer exposes the backend through `/api`

## Main User Flows

### Claim submission

1. User enters a message and optionally attaches supporting documents.
2. Files are uploaded first through `/upload`.
3. The chat request is then sent to `/chat` with `member_id` and `claim_category`.
4. The UI renders either:
   - a plain message
   - a structured answer
   - a claim decision card
   - an error message

### Admin claim update

1. User triggers an update-claim query from chat.
2. The UI opens an admin authentication panel.
3. The frontend sends the request to `/updateClaim` with `X-Admin-Password`.
4. The result is rendered as a success or failure card.

### Utility actions

The right-side panel also supports:

- deleting uploaded documents for a member
- uploading a policy file
- resetting the database
- switching to the test page

## Scripts

| Command | Use |
|---|---|
| `npm run dev` | Start local development server |
| `npm run build` | Build the production bundle |
| `npm run preview` | Preview the production build locally |
| `npm run lint` | Run ESLint |

## Related Files

| File | Use |
|---|---|
| [`../README.md`](../README.md) | Repository-level setup and project navigation |
| [`../backend/README.md`](../backend/README.md) | Backend API, environment, and local development details |
| [`../backend/ARCHITECTURE.md`](../backend/ARCHITECTURE.md) | End-to-end system and request flow diagrams |
