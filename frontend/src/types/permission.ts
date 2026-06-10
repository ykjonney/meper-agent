/**
 * Permission type definitions placeholder.
 * Real implementation in Story 1.4 (RBAC).
 */
export type Role = 'admin' | 'editor' | 'viewer'

export interface Permission {
  resource: string
  actions: string[]
}
