# syntax=docker/dockerfile:1
#
# Web image. Build context is the REPOSITORY ROOT (npm workspaces):
#   docker build -f apps/web/Dockerfile -t studypilot-web \
#     --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.com .
#   docker build -f apps/web/Dockerfile -t studypilot-web:dev --target dev .
#
# NEXT_PUBLIC_* values are compiled into the browser bundle at build time, so they must be
# supplied as build arguments. They are public by design: never pass a secret this way.

FROM node:24-slim AS base
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /repo

# --- Dependencies (cached until a package manifest changes) ----------------------------------
FROM base AS deps
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
RUN npm ci

# --- Development image: source is bind-mounted by Compose ------------------------------------
FROM deps AS dev
WORKDIR /repo/apps/web
COPY apps/web ./
ENV NODE_ENV=development
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]

# --- Production build ------------------------------------------------------------------------
FROM deps AS build
COPY apps/web apps/web
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_APP_NAME=StudyPilot
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_APP_NAME=$NEXT_PUBLIC_APP_NAME \
    NEXT_OUTPUT=standalone
RUN npm run build --workspace @studypilot/web

# --- Runtime image: standalone server only ---------------------------------------------------
FROM node:24-slim AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN groupadd --system --gid 10001 web && useradd --system --uid 10001 --gid web --no-create-home web
WORKDIR /app
COPY --from=build --chown=web:web /repo/apps/web/.next/standalone ./
COPY --from=build --chown=web:web /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=web:web /repo/apps/web/public ./apps/web/public
USER web
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/api/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"]
CMD ["node", "apps/web/server.js"]
