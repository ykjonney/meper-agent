/**
 * StartNodeConfig — 开始节点配置面板。
 */
import VariableListEditor from '../VariableListEditor'
import HelpHint from '../HelpHint'
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
      <div className="flex items-center gap-1">
        <span className="text-[10px] text-slate-400 font-medium">输入变量</span>
        <HelpHint text="定义工作流的初始输入变量，供下游节点引用。" />
      </div>
      <VariableListEditor
        value={outputVariables}
        onChange={handleOutputVariablesChange}
        nodeType="input"
      />
    </div>
  )
}
