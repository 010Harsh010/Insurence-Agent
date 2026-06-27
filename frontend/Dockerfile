# ---------------------------------------------------------------------------
# Frontend — React + Vite → nginx:alpine
#
# Two-stage build:
#   Stage 1 (builder): Install npm deps, run `vite build` → produces /app/dist
#   Stage 2 (runtime): nginx serves the static dist + reverse-proxies /api/ → backend
# ---------------------------------------------------------------------------

# ---------- Build Stage ----------
FROM node:22-alpine AS builder

WORKDIR /app

# Copy package files first for layer caching (only re-runs npm ci when package*.json changes)
COPY package*.json ./

RUN npm ci

ARG VITE_BACKEND_BASE
RUN echo $VITE_BACKEND_BASE


# Copy the rest of the source (build context is ./frontend)
COPY . .

RUN npm run build

# ---------- Runtime Stage ----------
FROM nginx:alpine

# nginx config: serves static files + proxies /api/* → backend:8000
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static build artifacts from Stage 1
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]