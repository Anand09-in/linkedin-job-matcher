# ── Frontend — dev server ────────────────────────────────────────────────────
# Phase 0/dev only. Phase 8 adds a multi-stage prod build (Vite build -> Nginx
# static serve, FR-9.2) once there's a real app to build.
FROM node:22-slim

WORKDIR /app
COPY package.json package-lock.json ./
# --legacy-peer-deps: openapi-typescript's peerDependencies still declare
# typescript "^5.x" (stale — hasn't caught up to TS 6 yet), which isn't an
# actual incompatibility for a build-time-only CLI tool like this.
RUN npm install --legacy-peer-deps

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
