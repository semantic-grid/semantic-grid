# syntax=docker/dockerfile:1.7

############################################
# Base (Bun)
############################################
FROM oven/bun:1.2 AS base
WORKDIR /repo
ENV NEXT_TELEMETRY_DISABLED=1

# These are your app coordinates
ARG APP_NAME=ape-gpt-app
ARG APP_DIR=apps/web

############################################
# Prune: produce a tiny context for this app
############################################
FROM base AS pruner
# Copy just what Turbo needs to compute the graph
COPY turbo.json package.json bun.lock* ./
COPY apps ./apps
COPY packages ./packages
RUN bunx turbo@^2 prune --scope="$APP_NAME" --docker

############################################
# Deps (dev): install using only pruned manifests
# Layer stays cached unless lock/manifests change
############################################
FROM base AS deps
# pruned manifests (json/lock only)
COPY --from=pruner /repo/out/json/ ./
# support text or binary bun lock
COPY --from=pruner /repo/out/bun.lock*  ./

# Use BuildKit cache mounts to speed re-installs
RUN --mount=type=cache,target=/root/.bun \
    --mount=type=cache,target=/root/.cache/bun \
    bun install --frozen-lockfile

############################################
# Build: copy code only after deps to keep cache
############################################
FROM base AS builder
# bring cached node_modules + pruned source
COPY --from=deps /repo/node_modules ./node_modules
COPY --from=pruner /repo/out/full/ ./

# Optional: ensure a local turbo; harmless if already present
RUN bun add -D turbo@^2.5.6

# Scope build to this app (prevents other workspaces from running)
RUN bunx turbo run build --filter="$APP_NAME"

############################################
# Deps (prod): small runtime node_modules
############################################
FROM base AS prod_deps
# Install prod deps from the same pruned manifests/lock
COPY --from=pruner /repo/out/json/ ./
COPY --from=pruner /repo/out/bun.lock*  ./
ENV BUN_INSTALL_DEV=false
RUN --mount=type=cache,target=/root/.bun \
    --mount=type=cache,target=/root/.cache/bun \
    bun install --frozen-lockfile --production

############################################
# Runtime (Node): tiny, predictable
############################################
FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
 ca-certificates  \
 && rm -rf /var/lib/apt/lists/*

# Non-root user
# RUN useradd -m nextjs && chown -R nextjs:nextjs /app
# USER nextjs

# 1) prod node_modules so require('next') works
COPY --from=prod_deps /repo/node_modules /app/node_modules

# 2) standalone server + assets (keep exact layout)
ARG APP_DIR=apps/web
COPY --from=builder /repo/${APP_DIR}/.next/standalone/ /app/
COPY --from=builder /repo/${APP_DIR}/.next/static     /app/.next/static
COPY --from=builder /repo/${APP_DIR}/public           /app/public

EXPOSE 3000

CMD ["node", "/app/server.js"]