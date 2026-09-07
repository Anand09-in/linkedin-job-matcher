# ── Frontend — dev server ────────────────────────────────────────────────────
# Phase 0/dev only. Phase 8 adds a multi-stage prod build (Vite build -> Nginx
# static serve, FR-9.2) once there's a real app to build.
FROM node:22-slim

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
