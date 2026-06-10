/**
 * Confirm dialog component placeholder.
 */
import { Modal } from 'antd'

export function ConfirmDialog({
  open,
  title,
  content,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title?: string
  content?: string
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Modal
      open={open}
      title={title ?? 'Confirm'}
      onOk={onConfirm}
      onCancel={onCancel}
    >
      <p>{content}</p>
    </Modal>
  )
}
