/**
 * Role API service — CRUD for dynamic roles.
 */
import { apiClient } from '../lib/api-client'
import type { Role } from './types'

export interface RoleCreatePayload {
  name: string
  display_name: string
  description?: string
  permissions: string[]
}

export interface RoleUpdatePayload {
  display_name?: string
  description?: string
  permissions?: string[]
}

export interface AllPermissionsResponse {
  permissions: string[]
  /** 权限键 → 中文名（后端 permission_labels 单一权威源下发） */
  labels?: Record<string, string>
}

export const roleApi = {
  list: () =>
    apiClient.get<Role[]>('/api/v1/roles'),

  create: (data: RoleCreatePayload) =>
    apiClient.post<Role>('/api/v1/roles', data),

  update: (id: string, data: RoleUpdatePayload) =>
    apiClient.patch<Role>(`/api/v1/roles/${id}`, data),

  delete: (id: string) =>
    apiClient.delete(`/api/v1/roles/${id}`),

  getAllPermissions: () =>
    apiClient.get<AllPermissionsResponse>('/api/v1/roles/permissions'),
}
