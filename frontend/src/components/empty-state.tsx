/**
 * Empty state component placeholder.
 */
export function EmptyState({ message = 'No data' }: { message?: string }) {
  return <div>{message}</div>
}
