/**
 * ProtectedRoute — guards routes that require authentication.
 *
 * Uses Outlet pattern so it can wrap a group of children routes.
 */
import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuthStore } from '../stores/auth-store'
import { PATHS } from './paths'

export function ProtectedRoute() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const location = useLocation()

  if (!isAuthenticated) {
    const redirect = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`${PATHS.LOGIN}?redirect=${redirect}`} replace />
  }

  return <Outlet />
}
