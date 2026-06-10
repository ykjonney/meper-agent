/**
 * Common shared types.
 */
export interface PaginationParams {
  page: number
  page_size: number
}

export interface PaginatedResponse<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

export interface ApiError {
  code: string
  message: string
  details: Record<string, unknown>
  request_id: string
  timestamp: string
}
