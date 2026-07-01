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
 * WS_BASE_URL connects DIRECTLY to the backend (port 8000), NOT through the
 * Vite proxy. WebSocket connections routed through Vite's http-proxy get cut
 * by the proxy's idle timeout (~60s), causing a connect→disconnect loop. WS
 * has no CORS restriction, so a direct connection is both possible and more
 * reliable. The host is taken from the page location (not hardcoded localhost)
 * so it works via localhost, an IP, or a domain.
 */
function required(current: string | undefined, fallback: string): string {
  if (current === undefined || current === '') return fallback
  return current
}

/**
 * Derive a DIRECT WebSocket URL to the backend (port 8000).
 *
 * - https://host  → wss://host:8000
 * - http://host   → ws://host:8000
 *
 * Uses the page's hostname (not localhost) so IP/domain access reaches the
 * backend on the same machine, and port 8000 (not the page port) to bypass
 * the Vite proxy entirely — avoiding its ~60s WebSocket idle disconnect.
 */
function defaultWsBaseUrl(): string {
  if (typeof window === 'undefined') return 'ws://localhost:8000'
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.hostname}:8000`
}

export const ENV = {
  // Empty in dev (service paths are already /api/v1/...; proxy handles them).
  // Absolute origin only for prod builds (e.g. https://api.example.com).
  API_BASE_URL: required(import.meta.env.VITE_API_BASE_URL, ''),
  // Direct connection to backend:8000, bypassing the Vite proxy.
  WS_BASE_URL: required(import.meta.env.VITE_WS_BASE_URL, defaultWsBaseUrl()),
} as const
