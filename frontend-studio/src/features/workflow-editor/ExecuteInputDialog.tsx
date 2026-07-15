/**
 * ExecuteInputDialog — 工作流执行前的输入参数弹窗。
 *
 * 读取 Start 节点的 output_variables（VariableDefinition[]），委托 WorkflowInputForm
 * 按类型渲染表单收集运行时输入值；提交时用 coerceValues 强转后交给 tasksApi.create。
 * 后端 StartNodeExecutor 按 name 从 task.input 取值，故这里只需按名塞值。
 *
 * file 类型：上传走 uploadFile（在 WorkflowInputForm 内部完成），后端 file_validator
 * 期望 value 为 FileRef id 字符串或 id 列表。
 */
import { useState, useEffect } from 'react'
import { Modal } from '../../components/ui'
import { type VariableDefinition } from './utils/variable-types'
import { buildDefaultValues, coerceValues } from './utils/workflow-input-values'
import WorkflowInputForm from './WorkflowInputForm'

interface Props {
  open: boolean
  variables: VariableDefinition[]
  onCancel: () => void
  onSubmit: (values: Record<string, unknown>) => void
}

export default function ExecuteInputDialog({ open, variables, onCancel, onSubmit }: Props) {
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    buildDefaultValues(variables),
  )
  const [valid, setValid] = useState(true)
  // 记录用户尝试过提交，用于驱动字段错误显示
  const [touched, setTouched] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // 每次打开 / variables 变化时重置表单（清空上次输入 / 错误）
  useEffect(() => {
    if (open) {
      setValues(buildDefaultValues(variables))
      setValid(true)
      setTouched(false)
      setSubmitError(null)
    }
  }, [open, variables])

  const handleSubmit = () => {
    setTouched(true)
    if (!valid) return
    const res = coerceValues(variables, values)
    if (res.error) {
      setSubmitError(res.error)
      return
    }
    setSubmitError(null)
    onSubmit(res.values)
  }

  return (
    <Modal
      open={open}
      title="执行参数"
      onCancel={onCancel}
      onOk={handleSubmit}
      okText="执行"
      cancelText="取消"
      width={520}
      okButtonProps={{ disabled: !valid }}
    >
      <div className="space-y-4">
        <p className="text-[11px] text-[#71717a]">
          开始节点定义了输入变量，请填入本次执行所需的参数。未填的可选变量将使用默认值。
        </p>

        <WorkflowInputForm
          variables={variables}
          value={values}
          onChange={setValues}
          onValidityChange={(v) => setValid(v)}
          showErrors={touched}
        />

        {submitError && (
          <div className="px-3 py-2 rounded-md bg-red-500/10 border border-red-500/20 text-[11px] text-red-400">
            {submitError}
          </div>
        )}
      </div>
    </Modal>
  )
}
