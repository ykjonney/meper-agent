/**
 * StartNodeConfig — 开始节点配置面板。
 */
import VariableListEditor from '../VariableListEditor'
import type { VariableDefinition } from '../utils/variable-types'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
}

export default function StartNodeConfig({ config, onChange }: Props) {
  const outputVariables = (config.output_variables as VariableDefinition[]) ?? []

  const handleOutputVariablesChange = (variables: VariableDefinition[]) => {
    onChange({ ...config, output_variables: variables })
  }

  return (
    <div className="space-y-3">
      <VariableListEditor
        value={outputVariables}
        onChange={handleOutputVariablesChange}
        nodeType="input"
      />
      <p className="text-[10px] text-[#71717a]">
        定义工作流的初始输入变量。下游节点可通过 VariableSelector 引用这些变量。
      </p>
    </div>
  )
}
