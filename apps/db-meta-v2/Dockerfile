FROM python:3.13-bookworm AS builder

# Copy uv from uv image
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /bin/

# UV settings
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=0 \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1

ARG PROJECT_DIR=apps/db-meta-v2

WORKDIR /app

# Install dependencies with uv cache
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=${PROJECT_DIR}/uv.lock,target=uv.lock \
    --mount=type=bind,source=${PROJECT_DIR}/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=packages/sg-models,target=packages/sg-models \
    uv sync --frozen --no-install-project

# Copy the project into the image
COPY ${PROJECT_DIR}/pyproject.toml ${PROJECT_DIR}/uv.lock /app/
COPY ${PROJECT_DIR}/src /app/src
COPY packages/sg-models /app/packages/sg-models

# Sync the project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

FROM python:3.13-slim-bookworm

COPY --from=builder --chown=nobody:nogroup /app /app

# Copy resource packages
ENV RESOURCES_DIR=/app/packages/resources
ENV PROVIDERS_DIR=/app/packages/resources/dbmeta_app/providers
COPY --chown=nobody:nogroup packages/resources/ /app/packages/resources/

EXPOSE 8000

ENV PATH="/app/.venv/bin:$PATH"
ENV MCP_TRANSPORT=http
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000

WORKDIR /app

USER nobody

CMD ["python", "-m", "db_meta_v2.server"]
