/**
 * Client-side request ID generator (UUID short format, matches backend).
 */
export function generateRequestId(): string {
  return crypto.randomUUID().replace(/-/g, '').slice(0, 8)
}
