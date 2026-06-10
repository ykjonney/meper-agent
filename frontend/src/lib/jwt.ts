/**
 * Lightweight JWT decode — extracts payload without verifying signature.
 *
 * Signature verification happens server-side; the frontend only reads claims.
 */
export interface JwtPayload {
  sub: string
  type: string
  role: string
  username: string
  iat: number
  exp: number
  [key: string]: unknown
}

/**
 * Decode a JWT access token and return the payload.
 * Returns null if the token is malformed.
 */
export function decodeAccessToken(token: string): JwtPayload | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null

    const base64Url = parts[1]
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join(''),
    )

    return JSON.parse(jsonPayload) as JwtPayload
  } catch {
    return null
  }
}

/**
 * Check whether a JWT access token is expired.
 */
export function isTokenExpired(token: string): boolean {
  const payload = decodeAccessToken(token)
  if (!payload) return true
  return Date.now() >= payload.exp * 1000
}
