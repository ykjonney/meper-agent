/**
 * Generic data-fetching hook placeholder.
 * Real implementation uses @tanstack/react-query in later stories.
 */
export function useRequest<T>() {
  return { data: null as T | null, loading: false, error: null }
}
