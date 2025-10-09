# ========= base runtime =========
FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENV=/app/.venv

# tools needed for building some deps + uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc g++ build-essential ca-certificates clang \
 && rm -rf /var/lib/apt/lists/*

# Install uv (Python package manager)
ADD https://astral.sh/uv/0.6.16/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.cargo/bin:/root/.local/bin:/usr/local/bin:${PATH}"

WORKDIR /app

# ========= copy app & packs =========
# Copy only db-meta app first (better layer caching)
COPY apps/db-meta/ /app/

# Bake SYSTEM PACKS into the image (Option A)
# Keep paths consistent with fm-app for reuse
COPY packages/resources/ /app/packages/resources/
COPY packages/client-configs/ /app/packages/client-configs/

# DO NOT copy client-configs here; they’ll be mounted at runtime (Option B)

# ========= install deps =========
# If using pyproject + uv in apps/db-meta
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen
ENV PATH="/app/.venv/bin:${PATH}"

# ========= runtime env =========
# Where db-meta should look for packs; fm-app and db-meta use the same defaults
ENV PACKS_RESOURCES_DIR=/app/packages

# Optional: service-specific envs (example)
# ENV DBMETA_DEFAULT_PROFILE=wh \
#     DBMETA_LOG_LEVEL=INFO

# Expose service port
EXPOSE 8081

# Optional healthcheck (assuming /health endpoint)
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -qO- http://127.0.0.1:8081/health || exit 1

# Start server (adjust if you have a different entrypoint)
# If your main file is e.g. dbmeta_app/main.py with FastAPI app object
# CMD ["uv", "run", "fastapi", "run", "dbmeta_app/main.py", "--host", "0.0.0.0", "--port", "8081"]