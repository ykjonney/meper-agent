/**
 * Strongly-typed environment accessor for the frontend.
 *
 * All Vite env vars must be declared in `src/env.d.ts` and prefixed with `VITE_`.
 */

const env = import.meta.env as {
  readonly VITE_API_BASE_URL: string
  readonly VITE_WS_BASE_URL: string
}

function required(key: keyof typeof env, fallback: string): string {
  const value = env[key]
  if (value === undefined || value === '') {
    return fallback
  }
  return value
}

export const ENV = {
  API_BASE_URL: required('VITE_API_BASE_URL', 'http://localhost:8000'),
  WS_BASE_URL: required('VITE_WS_BASE_URL', 'ws://localhost:8000'),
} as const
