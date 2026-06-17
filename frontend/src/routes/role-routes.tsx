/**
 * Route filtering based on user permissions.
 *
 * Routes can declare required permissions via the `handle.permission` field.
 * Routes without a permission requirement are always visible.
 */
import { useAuthStore } from '../stores/auth-store'

export interface RouteWithPermission {
  handle?: {
    permission?: string
    permissions?: string[]
  }
  children?: RouteWithPermission[]
  [key: string]: unknown
}

/**
 * Check if a user's permissions satisfy a route's permission requirement.
 */
function hasRoutePermission(
  route: RouteWithPermission,
  userPermissions: string[],
): boolean {
  const handle = route.handle
  if (!handle) return true

  if (handle.permission) {
    return userPermissions.includes(handle.permission)
  }
  if (handle.permissions) {
    return handle.permissions.some((p) => userPermissions.includes(p))
  }
  return true
}

/**
 * Filter routes based on the current user's permissions.
 * Returns a new array with inaccessible routes removed.
 */
export function filterRoutesByPermissions<T extends RouteWithPermission>(
  routes: T[],
): T[] {
  const userPermissions = useAuthStore.getState().user?.permissions ?? []

  return routes.filter((route) => {
    if (!hasRoutePermission(route, userPermissions)) return false

    // Also filter children if present
    if (route.children) {
      const filteredChildren = filterRoutesByPermissions(route.children)
      if (filteredChildren.length === 0 && route.children.length > 0) {
        return false // All children filtered out
      }
    }
    return true
  })
}
