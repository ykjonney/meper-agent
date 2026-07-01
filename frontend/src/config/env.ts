/**
 * Strongly-typed environment accessor for the frontend.
 *
 * Vite exposes `import.meta.env.VITE_*` at build time. In dev, the vite proxy
 * (vite.config.ts) forwards `/api` and `/ws` to the backend at port 8000, so a
 * relative baseURL works. For production builds, set VITE_API_BASE_URL to the
 * backend origin (e.g. https://api.example.com).
 *
 * IMPORTANT: service calls already include the `/api/v1` prefix (see
 * services/*-api.ts, e.g. `/api/v1/auth/login`). So API_BASE_URL must stay
 * EMPTY in dev — setting it to `/api/v1` would double the prefix and 404 every
 * request. Only set VITE_API_BASE_URL to an absolute origin for prod builds.
 *
 * WS_BASE_URL is derived from the current page location so it works regardless
 * of whether the app is reached via localhost, an IP, or a domain (HTTP or HTTPS).
 */
function required(current: string | undefined, fallback: string): string {
  if (current === undefined || current === '') return fallback
  return current
}

/**
 * Derive a WebSocket base URL from the current page location.
 *
 * - https://host:port  → wss://host:port
 * - http://host:port   → ws://host:port
 *
 * Keeps the same host:port the page was loaded from so the request reaches the
 * Vite proxy (dev) or the reverse proxy (prod) instead of a hardcoded
 * `localhost:8000` that only works on the developer's machine.
 */
function defaultWsBaseUrl(): string {
  if (typeof window === 'undefined') return 'ws://localhost:8000'
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}`
}

export const ENV = {
  // Empty in dev (service paths are already /api/v1/...; proxy handles them).
  // Absolute origin only for prod builds (e.g. https://api.example.com).
  API_BASE_URL: required(import.meta.env.VITE_API_BASE_URL, ''),
  // Derived from page location so IP/domain access works without config.
  WS_BASE_URL: required(import.meta.env.VITE_WS_BASE_URL, defaultWsBaseUrl()),
} as const
