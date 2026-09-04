/**
 * AgentInfoContext — agent_id → {name, model} 实时映射。
 *
 * WorkflowDesigner 拉取 agents 列表后注入，画布节点卡据此解析 Agent
 * 名称/模型展示——不依赖 config 里的选择时缓存（agent_name/agent_model），
 * 存量工作流节点无需重新选择即可正确显示。react-query 按 key 去重，
 * 与 AgentNodeConfig 的 agents 查询共享缓存。
 */
import { createContext, useContext } from 'react'

export interface AgentInfo {
  name: string
  model: string
}

export const AgentInfoContext = createContext<Record<string, AgentInfo>>({})

export function useAgentInfo(): Record<string, AgentInfo> {
  return useContext(AgentInfoContext)
}

/** tool_id → 工具名 实时映射（同上，节点卡不显示 ID 类不可读内容）。 */
export const ToolNameContext = createContext<Record<string, string>>({})

export function useToolNames(): Record<string, string> {
  return useContext(ToolNameContext)
}
