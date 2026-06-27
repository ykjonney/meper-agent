/**
 * Client-side request ID generator (UUID short format, matches backend middleware).
 * Fallback for non-secure contexts (HTTP + IP address).
 */
export function generateRequestId(): string {
  // crypto.randomUUID() only works in secure contexts (HTTPS or localhost)
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().replace(/-/g, '').slice(0, 8)
  }
  // Fallback: generate random hex string
  return Math.random().toString(16).slice(2, 10)
}
