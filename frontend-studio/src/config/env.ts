/**
 * Strongly-typed environment accessor for the studio (Vite).
 *
 * Vite exposes `import.meta.env.VITE_*` at build time. In dev, the vite proxy
 * (vite.config.ts) forwards `/api` and `/ws` to the backend at port 8000, so a
 * relative baseURL works. For production builds, set VITE_API_BASE_URL to the
 * backend origin (e.g. https://api.example.com/api/v1).
 *
 * IMPORTANT: service calls already include the `/api/v1` prefix (see
 * services/*-api.ts, e.g. `/api/v1/auth/login`). So API_BASE_URL must stay
 * EMPTY in dev — setting it to `/api/v1` would double the prefix and 404 every
 * request. Only set VITE_API_BASE_URL to an absolute origin for prod builds.
 */
function required(current: string | undefined, fallback: string): string {
  if (current === undefined || current === '') return fallback
  return current
}

export const ENV = {
  // Empty in dev (service paths are already /api/v1/...; proxy handles them).
  // Absolute origin only for prod builds (e.g. https://api.example.com).
  API_BASE_URL: required(import.meta.env.VITE_API_BASE_URL, ''),
  WS_BASE_URL: required(import.meta.env.VITE_WS_BASE_URL, 'ws://localhost:8000'),
} as const
