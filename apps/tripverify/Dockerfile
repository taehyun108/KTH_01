# TripVerify — 멀티스테이지 Docker 빌드 (Next.js standalone)
FROM node:22-bookworm-slim AS base
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable

FROM base AS deps
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
# standalone 출력만 복사
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public 2>/dev/null || true
# 네이티브 better-sqlite3 바이너리 포함
COPY --from=build /app/node_modules/better-sqlite3 ./node_modules/better-sqlite3
EXPOSE 3000
ENV PORT=3000 DATABASE_URL=/data/tripverify.sqlite
VOLUME ["/data"]
CMD ["node", "server.js"]
