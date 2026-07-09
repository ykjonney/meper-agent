/** Credential API — encrypted secrets for tool authentication. */
import { apiClient } from './api-client'

export type CredentialType = 'api_key' | 'bearer' | 'basic' | 'oauth2'

export interface Credential {
  _id: string
  user_id: string
  name: string
  type: CredentialType
  masked_data: Record<string, string>
  created_at: string
}

export interface CredentialCreate {
  name: string
  type: CredentialType
  data: Record<string, string>
}

export interface CredentialListResponse {
  items: Credential[]
  total: number
}

export const credentialsApi = {
  async list(): Promise<CredentialListResponse> {
    const res = await apiClient.get<CredentialListResponse>('/api/v1/credentials')
    return res.data
  },

  async create(body: CredentialCreate): Promise<Credential> {
    const res = await apiClient.post<Credential>('/api/v1/credentials', body)
    return res.data
  },

  async remove(id: string): Promise<void> {
    await apiClient.delete(`/api/v1/credentials/${id}`)
  },
}

export const credentialKeys = {
  all: ['credentials'] as const,
  lists: () => [...credentialKeys.all, 'list'] as const,
  list: () => [...credentialKeys.lists()] as const,
}
