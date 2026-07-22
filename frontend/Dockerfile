FROM node:22-alpine AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# ─── Dependencies ──────────────────────────────────────────────
FROM base AS deps
RUN apk add --no-cache libc6-compat
RUN corepack enable && corepack prepare pnpm@9 --activate
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# ─── Source (deps + app source, not built) ────────────────────
# Published as nexora-frontend-src so downstream products (NexoraCloud)
# can layer their own pages on top and run their own build, without needing
# the core source tree checked out.
FROM deps AS source
COPY . .

# ─── Development ───────────────────────────────────────────────
FROM source AS dev
EXPOSE 3000
CMD ["pnpm", "run", "dev"]

# ─── Builder ───────────────────────────────────────────────────
FROM source AS builder
RUN pnpm run build

# ─── Production runner ─────────────────────────────────────────
FROM base AS runner
ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
