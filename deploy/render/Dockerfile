# syntax=docker/dockerfile:1
# Render free tier: a free Render service is ONE web container, so this image
# runs the web app (Caddy) and the API together (see start.sh). Analyses run
# inline in the API (HARTRIAGE_CELERY_EAGER), so no separate worker is needed.
# Build from the repository root:  docker build -f deploy/render/Dockerfile .

# ---- web app ------------------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Python dependencies (same as the main Dockerfile) ------------------------
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY kb ./kb
COPY hartriage ./hartriage
RUN uv sync --frozen --no-dev --no-editable --reinstall-package hartriage

# ---- runtime ------------------------------------------------------------------
FROM python:3.13-slim
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=caddy:2-alpine /usr/bin/caddy /usr/bin/caddy
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=frontend /app/dist /srv
COPY deploy/render/Caddyfile /etc/caddy/Caddyfile
COPY deploy/render/start.sh /start.sh
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    XDG_DATA_HOME=/tmp XDG_CONFIG_HOME=/tmp
WORKDIR /app
USER app
CMD ["bash", "/start.sh"]
