FROM python:3.13-bookworm AS builder

# Copy uv from uv image
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /bin/

# UV settings
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=0 \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1

# Replicate repo structure so relative paths work
WORKDIR /build

# Copy sg-models first (needed for dependency resolution)
COPY packages/sg-models /build/packages/sg-models

# Copy project files
COPY apps/db-meta-v2/pyproject.toml apps/db-meta-v2/uv.lock /build/apps/db-meta-v2/

# Install dependencies with uv cache
WORKDIR /build/apps/db-meta-v2
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# Copy source code
COPY apps/db-meta-v2/src /build/apps/db-meta-v2/src

# Sync the project (installs the project itself)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

FROM python:3.13-slim-bookworm

# Copy built app (includes .venv with all dependencies)
COPY --from=builder --chown=nobody:nogroup /build/apps/db-meta-v2 /app
# Copy sg-models (local dependency)
COPY --from=builder --chown=nobody:nogroup /build/packages/sg-models /app/packages/sg-models

# Copy resource packages
ENV RESOURCES_DIR=/app/packages/resources
ENV PROVIDERS_DIR=/app/packages/resources/dbmeta_app/providers
COPY --chown=nobody:nogroup packages/resources/ /app/packages/resources/

EXPOSE 8000

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src:/app/packages/sg-models/src"
ENV MCP_TRANSPORT=http
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000

WORKDIR /app

USER nobody

CMD ["python", "-m", "db_meta_v2.server"]
