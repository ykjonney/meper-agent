/**
 * Workflow 发布前验证模块。
 *
 * 在发布工作流之前进行全面的验证检查，涵盖：
 * - 基本结构（start/end 节点、边引用、至少 1 条边）
 * - 节点配置（agent_id、tool_id、conditions、title 等必填字段）
 * - 变量引用（{{node_id.field}} 的 node_id 必须是上游节点、field 必须存在）
 * - DAG 连通性（孤立节点、循环引用）
 * - 未保存修改检查
 */
import type { WorkflowNode, WorkflowEdge } from '../../../services/workflows-api'
import { getEffectiveOutputVariables } from './node-output-variables'

/* ─── Types ─── */

export interface ValidationError {
  /** 唯一标识 */
  id: string
  /** 错误分类 */
  category: 'structure' | 'config' | 'variable' | 'dag'
  /** 严重级别 */
  level: 'error' | 'warning'
  /** 错误码 */
  code: string
  /** 人类可读的错误消息 */
  message: string
  /** 关联的节点 ID（可选） */
  nodeId?: string
  /** 额外详情 */
  details?: Record<string, unknown>
}

export interface ValidationResult {
  /** 是否通过验证（没有 error 级别的问题） */
  valid: boolean
  /** 所有错误列表 */
  errors: ValidationError[]
  /** 所有警告列表 */
  warnings: ValidationError[]
}

/* ─── Error Codes ─── */

export const VALIDATION_ERROR_CODES = {
  NO_START_OR_END: 'NO_START_OR_END',
  MISSING_NODE_IN_EDGE: 'MISSING_NODE_IN_EDGE',
  NO_EDGES: 'NO_EDGES',
  AGENT_MISSING_ID: 'AGENT_MISSING_ID',
  AGENT_MISSING_QUERY: 'AGENT_MISSING_QUERY',
  TOOL_MISSING_ID: 'TOOL_MISSING_ID',
  GATEWAY_NO_CONDITIONS: 'GATEWAY_NO_CONDITIONS',
  GATEWAY_INVALID_CONDITION: 'GATEWAY_INVALID_CONDITION',
  HUMAN_MISSING_TITLE: 'HUMAN_MISSING_TITLE',
  VARIABLE_INVALID_NODE: 'VARIABLE_INVALID_NODE',
  VARIABLE_INVALID_FIELD: 'VARIABLE_INVALID_FIELD',
  CYCLE_DETECTED: 'CYCLE_DETECTED',
  ORPHAN_NODE: 'ORPHAN_NODE',
  UNSAVED_CHANGES: 'UNSAVED_CHANGES',
} as const

/* ─── Main Entry ─── */

/**
 * 验证工作流是否可以发布。
 */
export function validateWorkflow(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  hasUnsavedChanges: boolean,
): ValidationResult {
  const allIssues: ValidationError[] = []

  // 0. 未保存修改检查
  if (hasUnsavedChanges) {
    allIssues.push({
      id: 'unsaved_changes',
      category: 'structure',
      level: 'error',
      code: VALIDATION_ERROR_CODES.UNSAVED_CHANGES,
      message: '工作流有未保存的修改，请先保存后再发布',
    })
  }

  // 1. 基本结构验证
  allIssues.push(...validateStructure(nodes, edges))

  // 如果基本结构都不满足，后续验证可能产生大量噪音，提前返回
  const hasStructuralErrors = allIssues.some(
    (i) => i.level === 'error' && i.category === 'structure',
  )
  if (hasStructuralErrors) {
    return buildResult(allIssues)
  }

  // 2. 节点配置验证
  allIssues.push(...validateNodeConfigs(nodes))

  // 3. DAG 连通性验证
  allIssues.push(...validateDagConnectivity(nodes, edges))

  // 4. 变量引用验证
  allIssues.push(...validateVariableReferences(nodes))

  return buildResult(allIssues)
}

/* ─── Structure Validation ─── */

function validateStructure(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
): ValidationError[] {
  const issues: ValidationError[] = []
  const nodeIds = new Set(nodes.map((n) => n.node_id))

  // 至少 1 个 start（end 节点可选）
  const startNodes = nodes.filter((n) => n.type === 'start')

  if (startNodes.length === 0) {
    issues.push({
      id: 'no_start',
      category: 'structure',
      level: 'error',
      code: VALIDATION_ERROR_CODES.NO_START_OR_END,
      message: '工作流必须包含开始(start)节点',
    })
  }

  // end 节点缺失只给 warning（引擎不依赖 end 节点）
  const endNodes = nodes.filter((n) => n.type === 'end')
  if (endNodes.length === 0 && nodes.length >= 2) {
    issues.push({
      id: 'no_end',
      category: 'structure',
      level: 'warning',
      code: VALIDATION_ERROR_CODES.NO_START_OR_END,
      message: '工作流没有结束(end)节点，建议添加以明确标识工作流终点',
    })
  }

  // 所有边引用的 node_id 必须存在
  for (const edge of edges) {
    if (!nodeIds.has(edge.source)) {
      issues.push({
        id: `edge_missing_source_${edge.edge_id}`,
        category: 'structure',
        level: 'error',
        code: VALIDATION_ERROR_CODES.MISSING_NODE_IN_EDGE,
        message: `边 "${edge.label || edge.edge_id}" 引用了不存在的源节点 "${edge.source}"`,
        details: { edgeId: edge.edge_id, missingNodeId: edge.source },
      })
    }
    if (!nodeIds.has(edge.target)) {
      issues.push({
        id: `edge_missing_target_${edge.edge_id}`,
        category: 'structure',
        level: 'error',
        code: VALIDATION_ERROR_CODES.MISSING_NODE_IN_EDGE,
        message: `边 "${edge.label || edge.edge_id}" 引用了不存在的目标节点 "${edge.target}"`,
        details: { edgeId: edge.edge_id, missingNodeId: edge.target },
      })
    }
  }

  // 至少 1 条边 或 config.next_nodes 连接
  const hasNextNodeRefs = nodes.some(
    (n) => {
      const nextNodes = (n.config as Record<string, unknown>)?.next_nodes
      return Array.isArray(nextNodes) && nextNodes.length > 0
    },
  )
  if (edges.length === 0 && !hasNextNodeRefs && nodes.length >= 2) {
    issues.push({
      id: 'no_edges',
      category: 'structure',
      level: 'error',
      code: VALIDATION_ERROR_CODES.NO_EDGES,
      message: '工作流至少需要 1 条连接来串联节点',
    })
  }

  return issues
}

/* ─── Node Config Validation ─── */

function validateNodeConfigs(nodes: WorkflowNode[]): ValidationError[] {
  const issues: ValidationError[] = []

  for (const node of nodes) {
    const config = node.config || {}
    const nodeLabel = node.label || node.type

    switch (node.type) {
      case 'agent': {
        if (!config.agent_id) {
          issues.push({
            id: `agent_missing_id_${node.node_id}`,
            category: 'config',
            level: 'error',
            code: VALIDATION_ERROR_CODES.AGENT_MISSING_ID,
            message: `Agent 节点 "${nodeLabel}" 必须选择一个 Agent`,
            nodeId: node.node_id,
          })
        }
        const query = config.input_query
        if (!query || (typeof query === 'string' && query.trim() === '')) {
          issues.push({
            id: `agent_missing_query_${node.node_id}`,
            category: 'config',
            level: 'error',
            code: VALIDATION_ERROR_CODES.AGENT_MISSING_QUERY,
            message: `Agent 节点 "${nodeLabel}" 必须填写查询内容`,
            nodeId: node.node_id,
          })
        }
        break
      }
      case 'tool': {
        if (!config.tool_id) {
          issues.push({
            id: `tool_missing_id_${node.node_id}`,
            category: 'config',
            level: 'error',
            code: VALIDATION_ERROR_CODES.TOOL_MISSING_ID,
            message: `工具节点 "${nodeLabel}" 必须选择一个工具`,
            nodeId: node.node_id,
          })
        }
        break
      }
      case 'gateway': {
        const conditions = config.conditions
        if (!Array.isArray(conditions) || conditions.length === 0) {
          issues.push({
            id: `gateway_no_conditions_${node.node_id}`,
            category: 'config',
            level: 'error',
            code: VALIDATION_ERROR_CODES.GATEWAY_NO_CONDITIONS,
            message: `网关节点 "${nodeLabel}" 至少需要 1 个条件分支`,
            nodeId: node.node_id,
          })
        } else {
          const validOperators = new Set(['==', '!=', '>', '<', '>=', '<=', 'contains', 'not_contains'])
          // 比较符号黑名单：expression 不允许内联比较，必须用「判断符」下拉选择
          const comparisonSymbols = ['==', '!=', '>=', '<=', '>', '<']
          // 合法 expression：strip 后是单一变量引用 {{ xxx }}
          const singleVarRe = /^\{\{.+\}\}$/
          ;(conditions as Array<Record<string, unknown>>).forEach((cond, idx) => {
            const expression = (cond.expression as string) ?? ''
            const op = (cond.operator as string) ?? ''
            const target = (cond.target as string) ?? ''
            const trimmedExpr = expression.trim()
            // 缺失字段校验
            const missing: string[] = []
            if (!trimmedExpr) missing.push('表达式')
            // operator 缺省视为合法（向后兼容默认 ==）；仅当显式填写且不在白名单时报错
            if (op && !validOperators.has(op)) missing.push('判断符')
            if (!target) missing.push('目标节点')
            if (missing.length > 0) {
              issues.push({
                id: `gateway_invalid_condition_${node.node_id}_${idx}`,
                category: 'config',
                level: 'error',
                code: VALIDATION_ERROR_CODES.GATEWAY_INVALID_CONDITION,
                message: `网关节点 "${nodeLabel}" 条件 #${idx + 1} 缺少：${missing.join('、')}`,
                nodeId: node.node_id,
              })
            }
            // 防内联校验：expression 必须是单一变量引用，禁止内联比较符号或多表达式
            const hasSymbol = comparisonSymbols.some((sym) => trimmedExpr.includes(sym))
            const isSingleVar = singleVarRe.test(trimmedExpr)
            if (trimmedExpr && (hasSymbol || !isSingleVar)) {
              issues.push({
                id: `gateway_invalid_expression_${node.node_id}_${idx}`,
                category: 'config',
                level: 'error',
                code: VALIDATION_ERROR_CODES.GATEWAY_INVALID_CONDITION,
                message: `网关节点 "${nodeLabel}" 条件 #${idx + 1} 表达式必须是单一变量引用（如 {{ node_id.field }}），请勿内联比较符号，比较逻辑请用「判断符」下拉选择`,
                nodeId: node.node_id,
              })
            }
          })
        }
        break
      }
      case 'human': {
        if (!config.title) {
          issues.push({
            id: `human_missing_title_${node.node_id}`,
            category: 'config',
            level: 'error',
            code: VALIDATION_ERROR_CODES.HUMAN_MISSING_TITLE,
            message: `人工审批节点 "${nodeLabel}" 必须设置审批标题`,
            nodeId: node.node_id,
          })
        }
        break
      }
    }
  }

  return issues
}

/* ─── DAG Connectivity Validation ─── */

/**
 * 检测从 start 节点不可达的孤立节点（warning 级别）。
 */
function findOrphanNodes(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
): ValidationError[] {
  const issues: ValidationError[] = []
  const connectedFromStart = new Set<string>()

  // BFS from start nodes
  const queue: string[] = []
  for (const node of nodes) {
    if (node.type === 'start') {
      queue.push(node.node_id)
      connectedFromStart.add(node.node_id)
    }
  }

  let head = 0
  while (head < queue.length) {
    const current = queue[head++]
    for (const edge of edges) {
      if (edge.source === current && !connectedFromStart.has(edge.target)) {
        connectedFromStart.add(edge.target)
        queue.push(edge.target)
      }
    }
  }

  // 找到不可达的节点（排除 start 节点本身）
  const orphans = nodes.filter(
    (n) => !connectedFromStart.has(n.node_id),
  )

  for (const orphan of orphans) {
    issues.push({
      id: `orphan_node_${orphan.node_id}`,
      category: 'dag',
      level: 'warning',
      code: VALIDATION_ERROR_CODES.ORPHAN_NODE,
      message: `节点 "${orphan.label || orphan.type}" 从开始节点不可达，执行时将被跳过`,
      nodeId: orphan.node_id,
    })
  }

  return issues
}

/**
 * 使用 DFS + 递归栈检测循环引用。
 */
function detectCycle(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
): string[] {
  // 构建邻接表
  const adj = new Map<string, string[]>()
  for (const node of nodes) {
    adj.set(node.node_id, [])
  }
  for (const edge of edges) {
    const list = adj.get(edge.source)
    if (list) {
      list.push(edge.target)
    }
  }

  const visited = new Set<string>()
  const recStack = new Set<string>()
  const path: string[] = []

  function dfs(nodeId: string): string[] | null {
    if (recStack.has(nodeId)) {
      // 找到环，从当前路径中截取环的部分
      const cycleStart = path.indexOf(nodeId)
      return path.slice(cycleStart).concat(nodeId)
    }
    if (visited.has(nodeId)) return null

    visited.add(nodeId)
    recStack.add(nodeId)
    path.push(nodeId)

    const neighbors = adj.get(nodeId) ?? []
    for (const neighbor of neighbors) {
      const cycle = dfs(neighbor)
      if (cycle) return cycle
    }

    recStack.delete(nodeId)
    path.pop()
    return null
  }

  for (const node of nodes) {
    if (!visited.has(node.node_id)) {
      const cycle = dfs(node.node_id)
      if (cycle) return cycle
    }
  }

  return []
}

function validateDagConnectivity(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
): ValidationError[] {
  const issues: ValidationError[] = []

  // 孤立节点检测（warning）
  issues.push(...findOrphanNodes(nodes, edges))

  // 循环引用检测（error）
  const cycle = detectCycle(nodes, edges)
  if (cycle.length > 0) {
    const nodeMap = new Map(nodes.map((n) => [n.node_id, n]))
    const cycleLabels = cycle.map((id) => {
      const node = nodeMap.get(id)
      return node ? (node.label || node.type) : id
    })

    issues.push({
      id: 'cycle_detected',
      category: 'dag',
      level: 'error',
      code: VALIDATION_ERROR_CODES.CYCLE_DETECTED,
      message: `检测到循环引用: ${cycleLabels.join(' → ')}`,
      details: { cycleNodes: cycle },
    })
  }

  return issues
}

/* ─── Variable Reference Validation ─── */

/** 匹配 {{node_id.field}} 模板变量 */
const VARIABLE_REGEX = /\{\{(\w+)\.(\w+)\}\}/g

function validateVariableReferences(
  nodes: WorkflowNode[],
): ValidationError[] {
  const issues: ValidationError[] = []
  const nodeMap = new Map(nodes.map((n) => [n.node_id, n]))

  for (const node of nodes) {
    const config = node.config || {}
    const nodeLabel = node.label || node.type

    // 收集需要检查的配置字段
    const fieldsToCheck = collectConfigFieldsToCheck(config)

    for (const { key, value } of fieldsToCheck) {
      if (typeof value !== 'string') continue

      const varIssues = checkVariableInString(
        value,
        node.node_id,
        nodeLabel,
        key,
        nodeMap,
      )
      issues.push(...varIssues)
    }
  }

  return issues
}

function collectConfigFieldsToCheck(
  config: Record<string, unknown>,
): Array<{ key: string; value: unknown }> {
  const fields: Array<{ key: string; value: unknown }> = []

  // 直接字符串字段
  const stringKeys = [
    'input_prompt',
    'input_query',
    'result_mapping',
  ]

  for (const key of stringKeys) {
    if (config[key] != null) {
      fields.push({ key, value: config[key] })
    }
  }

  // params 对象（值可能是字符串）
  if (config.params && typeof config.params === 'object') {
    const params = config.params as Record<string, unknown>
    for (const [k, v] of Object.entries(params)) {
      if (typeof v === 'string') {
        fields.push({ key: `params.${k}`, value: v })
      }
    }
  }

  // conditions 数组（每个 condition 的 expression）
  if (Array.isArray(config.conditions)) {
    for (let i = 0; i < config.conditions.length; i++) {
      const cond = config.conditions[i]
      if (cond && typeof cond === 'object') {
        const expression = (cond as Record<string, unknown>).expression
        if (typeof expression === 'string') {
          fields.push({ key: `conditions[${i}].expression`, value: expression })
        }
      }
    }
  }

  // output_mapping / input_mapping 对象
  const mappingKeys = ['output_mapping', 'input_mapping']
  for (const mk of mappingKeys) {
    if (config[mk] && typeof config[mk] === 'object') {
      const mapping = config[mk] as Record<string, unknown>
      for (const [k, v] of Object.entries(mapping)) {
        if (typeof v === 'string') {
          fields.push({ key: `${mk}.${k}`, value: v })
        }
      }
    }
  }

  return fields
}

function checkVariableInString(
  text: string,
  currentNodeId: string,
  currentNodeLabel: string,
  fieldKey: string,
  nodeMap: Map<string, WorkflowNode>,
): ValidationError[] {
  const issues: ValidationError[] = []
  let match: RegExpExecArray | null

  // 重置正则 lastIndex（因为是全局正则）
  VARIABLE_REGEX.lastIndex = 0

  while ((match = VARIABLE_REGEX.exec(text)) !== null) {
    const [, refNodeId, fieldName] = match

    // 特殊变量 "input" 表示工作流的输入参数，跳过验证
    if (refNodeId === 'input') continue

    // 检查 1: node_id 是否存在
    if (!nodeMap.has(refNodeId)) {
      issues.push({
        id: `var_${currentNodeId}_${refNodeId}_${fieldName}_${fieldKey}`,
        category: 'variable',
        level: 'error',
        code: VALIDATION_ERROR_CODES.VARIABLE_INVALID_NODE,
        message: `节点 "${currentNodeLabel}" 引用了不存在的节点 "${refNodeId}"（字段: ${fieldKey}）`,
        nodeId: currentNodeId,
        details: { reference: `{{${refNodeId}.${fieldName}}}`, fieldKey },
      })
      continue
    }

    // 检查 2: field 是否存在于该节点的输出字段
    const refNode = nodeMap.get(refNodeId)!
    const outputFields = getEffectiveOutputVariables(refNode)
    const fieldExists = outputFields.some(
      (f) => f.name === fieldName,
    )

    if (!fieldExists) {
      const availableFields = outputFields.map((f) => f.name)
      issues.push({
        id: `var_${currentNodeId}_${refNodeId}_${fieldName}_${fieldKey}`,
        category: 'variable',
        level: 'error',
        code: VALIDATION_ERROR_CODES.VARIABLE_INVALID_FIELD,
        message: `节点 "${currentNodeLabel}" 引用了 "${refNodeId}.${fieldName}"，但该节点没有此输出字段（字段: ${fieldKey}）`,
        nodeId: currentNodeId,
        details: {
          reference: `{{${refNodeId}.${fieldName}}}`,
          fieldKey,
          availableFields,
        },
      })
    }
  }

  return issues
}

/* ─── Helper ─── */

function buildResult(allIssues: ValidationError[]): ValidationResult {
  const errors = allIssues.filter((i) => i.level === 'error')
  const warnings = allIssues.filter((i) => i.level === 'warning')
  return {
    valid: errors.length === 0,
    errors,
    warnings,
  }
}
