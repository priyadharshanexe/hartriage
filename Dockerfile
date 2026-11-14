# syntax=docker/dockerfile:1

# ---- build stage: resolve and install dependencies into /app/.venv ----------
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /src

# Dependencies first, so this layer is cached until uv.lock changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Then the application itself (with the KB articles), as a regular package.
COPY README.md ./
COPY kb ./kb
COPY hartriage ./hartriage
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --reinstall-package hartriage
# --reinstall-package: uv caches the built package; without it a source-only
# change could ship the previously cached build.


# ---- runtime stage: Python, the virtualenv and the demo tools, as non-root ---
FROM python:3.13-slim AS runtime

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
# The fake helpdesk and the sample files, for the local demo stack only.
COPY --chown=app:app tools /app/tools

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]

CMD ["uvicorn", "--factory", "hartriage.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers"]
