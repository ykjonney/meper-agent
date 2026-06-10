/**
 * Loading spinner component placeholder.
 */
import { Spin } from 'antd'

export function LoadingSpinner({ tip }: { tip?: string }) {
  return <Spin tip={tip} />
}
