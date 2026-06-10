# syntax=docker/dockerfile:1.7

# --- Build stage ---
FROM node:22-alpine AS builder

WORKDIR /app

# Leverage layer caching: copy lockfile first
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and build
COPY . .
RUN npm run build

# --- Runtime stage: nginx serves the SPA ---
FROM nginx:alpine AS runtime

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Custom nginx config for SPA fallback
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
