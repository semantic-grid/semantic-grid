# syntax=docker/dockerfile:1.7

############################################
# Base (Bun)
############################################
FROM oven/bun:1.2 AS base
WORKDIR /repo
ENV NEXT_TELEMETRY_DISABLED=1

ARG APP_NAME=cms
ARG APP_DIR=apps/cms
ENV APP_NAME=${APP_NAME}
ENV APP_DIR=${APP_DIR}

############################################
# Prune
############################################
FROM base AS pruner
COPY turbo.json package.json bun.lock* ./
COPY apps ./apps
COPY packages ./packages
RUN bunx turbo@2.5.6 prune --scope="$APP_NAME" --docker

############################################
# Deps (dev)
############################################
FROM oven/bun:1.2 AS deps
WORKDIR /repo
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=pruner /repo/out/json/ ./
COPY --from=pruner /repo/out/bun.lock* ./
ENV BUN_INSTALL_DEV=false
RUN --mount=type=cache,target=/root/.bun \
    --mount=type=cache,target=/root/.cache/bun \
    bun install --ignore-scripts

############################################
# Build
############################################
FROM base AS builder
COPY --from=deps /repo/node_modules ./node_modules
COPY --from=pruner /repo/out/full/ ./

RUN bun add -D turbo@2.5.6
RUN bunx turbo run build --filter="$APP_NAME"

############################################
# Runtime (Payload official-style Next standalone)
############################################
FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000

# create non-root user like in official payload example
RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs

ARG APP_DIR=apps/cms

# COPY --from=builder --chown=nextjs:nodejs /repo/${APP_DIR}/public ./public

# --- public (optional) ---
# COPY --from=builder /repo/${APP_DIR}/public ./public

# prepare .next folder for static cache
RUN mkdir .next && chown nextjs:nodejs .next

# --- standalone server + static files ---
COPY --from=builder --chown=nextjs:nodejs /repo/${APP_DIR}/.next/standalone ./

WORKDIR /app/apps/cms

COPY --from=builder --chown=nextjs:nodejs /repo/${APP_DIR}/.next/static ./.next/static
COPY --from=deps /repo/node_modules ./node_modules

# Copy migrations folder
COPY --from=builder --chown=nextjs:nodejs /repo/${APP_DIR}/src/migrations ./src/migrations

USER nextjs
EXPOSE 3000

# From official Payload docs: Next standalone outputs server.js
CMD ["node", "server.js"]