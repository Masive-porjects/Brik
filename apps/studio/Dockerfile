# syntax=docker/dockerfile:1
# Studio (Next.js) — build context = raiz del repo.
# El workspace de bun exige bun.lock + los package.json de apps/* en el
# contexto; por eso el contexto no puede ser apps/studio.

# ── deps: bun instala el workspace respetando bun.lock ──────────────────────
FROM oven/bun:1 AS deps
WORKDIR /app
COPY package.json bun.lock ./
COPY apps/studio/package.json apps/studio/package.json
COPY apps/agent/package.json apps/agent/package.json
RUN bun install --frozen-lockfile

# ── build: toolchain real de Node para tsc + next build ─────────────────────
FROM node:20-slim AS build
WORKDIR /app
COPY --from=deps /app ./
COPY apps/agent ./apps/agent
COPY apps/studio ./apps/studio

# NEXT_PUBLIC_* se inlinean en el bundle durante `next build`: la URL del
# backend es un build-arg, no una env de runtime.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# @midimastering/agent apunta a dist/: hay que compilarlo antes de next build
# (mismo paso que el script "build" de apps/studio/package.json).
RUN node_modules/.bin/tsc -p apps/agent/tsconfig.json \
    && cd apps/studio && node ../../node_modules/next/dist/bin/next build

# ── runner: salida standalone de Next (solo lo que tracing detecta) ──────────
FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
# Docker setea HOSTNAME=<container-id> y el server standalone de Next lo usa
# como bind address — sin esto escucha solo en eth0 y localhost queda muerto.
ENV HOSTNAME=0.0.0.0

COPY --from=build /app/apps/studio/.next/standalone ./
COPY --from=build /app/apps/studio/.next/static ./apps/studio/.next/static
COPY --from=build /app/apps/studio/public ./apps/studio/public

EXPOSE 3000
CMD ["node", "apps/studio/server.js"]
