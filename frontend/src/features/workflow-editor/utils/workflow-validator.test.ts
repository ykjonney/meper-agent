/**
 * Workflow 验证器测试用例。
 *
 * 测试覆盖：
 * - 基本结构验证（start/end 节点、边引用）
 * - 节点配置验证（agent_id、tool_id、conditions、title）
 * - 变量引用验证（{{node_id.field}} 有效性）
 * - DAG 连通性（孤立节点、循环引用）
 * - 未保存修改检查
 */
import { describe, it, expect } from 'vitest'
import { validateWorkflow, VALIDATION_ERROR_CODES } from './workflow-validator'
import type { WorkflowNode, WorkflowEdge } from '../../../services/workflows-api'

/* ─── Test Helpers ─── */

const createNode = (
  id: string,
  type: string,
  config: Record<string, unknown> = {},
): WorkflowNode => ({
  node_id: id,
  type,
  label: `${type}_${id}`,
  config,
  position: { x: 0, y: 0 },
})

const createEdge = (
  id: string,
  source: string,
  target: string,
  label = '',
): WorkflowEdge => ({
  edge_id: id,
  source,
  target,
  label,
  condition: null,
})

/* ─── Valid Workflow ─── */

describe('validateWorkflow - valid cases', () => {
  it('should pass a minimal valid workflow', () => {
    const nodes = [
      createNode('node1', 'start', { input_schema: {} }),
      createNode('node2', 'end', { output_mapping: {} }),
    ]
    const edges = [createEdge('edge1', 'node1', 'node2')]

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(true)
    expect(result.errors).toHaveLength(0)
    expect(result.warnings).toHaveLength(0)
  })

  it('should pass a workflow with all node types properly configured', () => {
    const nodes = [
      createNode('node1', 'start', { input_schema: {} }),
      createNode('node2', 'agent', {
        agent_id: 'agent_123',
        input_query: '{{input.query}}',
        input_prompt: '分析以下数据',
        temperature: 0.7,
      }),
      createNode('node3', 'end', { output_mapping: {} }),
    ]
    const edges = [
      createEdge('edge1', 'node1', 'node2'),
      createEdge('edge2', 'node2', 'node3'),
    ]

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(true)
    expect(result.errors).toHaveLength(0)
  })
})

/* ─── Unsaved Changes Check ─── */

describe('validateWorkflow - unsaved changes', () => {
  it('should error when hasUnsavedChanges is true', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'end'),
    ]
    const edges = [createEdge('edge1', 'node1', 'node2')]

    const result = validateWorkflow(nodes, edges, true)

    expect(result.valid).toBe(false)
    expect(result.errors).toHaveLength(1)
    expect(result.errors[0].code).toBe(VALIDATION_ERROR_CODES.UNSAVED_CHANGES)
    expect(result.errors[0].message).toContain('未保存')
  })
})

/* ─── Structure Validation ─── */

describe('validateWorkflow - structure', () => {
  it('should error when missing start node', () => {
    const nodes = [
      createNode('node1', 'end'),
    ]
    const edges: WorkflowEdge[] = []

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.NO_START_OR_END)).toBe(true)
  })

  it('should warn when missing end node', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'agent'),
    ]
    const edges: WorkflowEdge[] = []

    const result = validateWorkflow(nodes, edges, false)

    // end 节点缺失只给 warning，不算 error（需 >=2 节点才触发）
    expect(result.valid).toBe(true)
    expect(result.warnings.some((w) => w.code === VALIDATION_ERROR_CODES.NO_START_OR_END)).toBe(true)
  })

  it('should error when no edges', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'end'),
    ]
    const edges: WorkflowEdge[] = []

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.NO_EDGES)).toBe(true)
  })

  it('should error when edge references non-existent source node', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'end'),
    ]
    const edges = [createEdge('edge1', 'nonexistent', 'node2')]

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.MISSING_NODE_IN_EDGE)).toBe(true)
  })

  it('should error when edge references non-existent target node', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'end'),
    ]
    const edges = [createEdge('edge1', 'node1', 'nonexistent')]

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.MISSING_NODE_IN_EDGE)).toBe(true)
  })
})

/* ─── Node Config Validation ─── */

describe('validateWorkflow - node configs', () => {
  const validBaseNodes = [
    createNode('node1', 'start'),
    createNode('node4', 'end'),
  ]
  const validBaseEdges = [
    createEdge('edge1', 'node1', 'node2'),
    createEdge('edge2', 'node2', 'node4'),
  ]

  it('should error when agent node missing agent_id', () => {
    const nodes = [
      ...validBaseNodes,
      createNode('node2', 'agent', { input_query: '{{input.query}}' }),
    ]
    const edges = validBaseEdges

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.AGENT_MISSING_ID)).toBe(true)
  })

  it('should error when agent node missing input_query (user_query)', () => {
    const nodes = [
      ...validBaseNodes,
      createNode('node2', 'agent', { agent_id: 'agent_123', input_prompt: 'test' }),
    ]
    const edges = validBaseEdges

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.AGENT_MISSING_QUERY)).toBe(true)
    // 消息应只提"查询"，不暴露内部变量名 user_query
    const err = result.errors.find((e) => e.code === VALIDATION_ERROR_CODES.AGENT_MISSING_QUERY)!
    expect(err.message).toContain('查询')
    expect(err.message).not.toContain('user_query')
  })

  it('should error when tool node missing tool_id', () => {
    const nodes = [
      ...validBaseNodes,
      createNode('node2', 'tool', { params: {} }),
    ]
    const edges = validBaseEdges

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.TOOL_MISSING_ID)).toBe(true)
  })

  it('should error when gateway node has no conditions', () => {
    const nodes = [
      ...validBaseNodes,
      createNode('node2', 'gateway', { conditions: [] }),
    ]
    const edges = validBaseEdges

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.GATEWAY_NO_CONDITIONS)).toBe(true)
  })

  it('should error when human node missing title', () => {
    const nodes = [
      ...validBaseNodes,
      createNode('node2', 'human', { description: 'test' }),
    ]
    const edges = validBaseEdges

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.HUMAN_MISSING_TITLE)).toBe(true)
  })

  it('should pass when all nodes have required configs', () => {
    const nodes = [
      ...validBaseNodes,
      createNode('node2', 'agent', { agent_id: 'agent_123', input_query: '{{input.query}}', input_prompt: 'test' }),
    ]
    const edges = validBaseEdges

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(true)
  })
})

/* ─── DAG Connectivity ─── */

describe('validateWorkflow - DAG connectivity', () => {
  it('should warn about orphan nodes', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'agent', { agent_id: 'agent_123', input_query: '{{input.q}}' }),
      createNode('node3', 'end'),
      createNode('node4', 'agent', { agent_id: 'agent_456', input_query: '{{input.q}}' }), // orphan
    ]
    const edges = [
      createEdge('edge1', 'node1', 'node2'),
      createEdge('edge2', 'node2', 'node3'),
    ]

    const result = validateWorkflow(nodes, edges, false)

    // Should still be valid (orphan is a warning)
    expect(result.valid).toBe(true)
    expect(result.warnings.some((e) => e.code === VALIDATION_ERROR_CODES.ORPHAN_NODE)).toBe(true)
    expect(result.warnings.some((e) => e.nodeId === 'node4')).toBe(true)
  })

  it('should error on cycle detection', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'agent', { agent_id: 'agent_123', input_query: '{{input.q}}' }),
      createNode('node3', 'end'),
    ]
    const edges = [
      createEdge('edge1', 'node1', 'node2'),
      createEdge('edge2', 'node2', 'node3'),
      createEdge('edge3', 'node3', 'node1'), // cycle!
    ]

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.CYCLE_DETECTED)).toBe(true)
  })

  it('should detect complex cycle', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'agent', { agent_id: 'agent_123', input_query: '{{input.q}}' }),
      createNode('node3', 'gateway', { conditions: [{ expression: 'true' }] }),
      createNode('node4', 'end'),
    ]
    const edges = [
      createEdge('edge1', 'node1', 'node2'),
      createEdge('edge2', 'node2', 'node3'),
      createEdge('edge3', 'node3', 'node2'), // back edge creates cycle
      createEdge('edge4', 'node3', 'node4'),
    ]

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.CYCLE_DETECTED)).toBe(true)
  })
})

/* ─── Variable Reference Validation ─── */

describe('validateWorkflow - variable references', () => {
  it('should error when referencing non-existent node', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'agent', {
        agent_id: 'agent_123',
        input_query: '{{input.q}}',
        input_prompt: '{{nonexistent.response}}',
      }),
      createNode('node3', 'end'),
    ]
    const edges = [
      createEdge('edge1', 'node1', 'node2'),
      createEdge('edge2', 'node2', 'node3'),
    ]

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.VARIABLE_INVALID_NODE)).toBe(true)
  })

  it('should error when referencing non-existent field', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'agent', {
        agent_id: 'agent_123',
        input_query: '{{input.q}}',
        input_prompt: '{{node1.nonexistent_field}}',
      }),
      createNode('node3', 'end'),
    ]
    const edges = [
      createEdge('edge1', 'node1', 'node2'),
      createEdge('edge2', 'node2', 'node3'),
    ]

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.code === VALIDATION_ERROR_CODES.VARIABLE_INVALID_FIELD)).toBe(true)
  })

  it('should accept {{input.field}} special variable', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'agent', {
        agent_id: 'agent_123',
        input_query: '{{input.user_query}}',
        input_prompt: 'test',
      }),
      createNode('node3', 'end'),
    ]
    const edges = [
      createEdge('edge1', 'node1', 'node2'),
      createEdge('edge2', 'node2', 'node3'),
    ]

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(true)
  })

  it('should accept valid variable reference to upstream node', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'agent', {
        agent_id: 'agent_123',
        input_query: '{{node1.input}}',
        input_prompt: 'test',
      }),
      createNode('node3', 'end'),
    ]
    const edges = [
      createEdge('edge1', 'node1', 'node2'),
      createEdge('edge2', 'node2', 'node3'),
    ]

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(true)
  })

  it('should validate variables in conditions expressions', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'gateway', {
        conditions: [
          { expression: '{{node1.input}} == "test"' },
        ],
        default_branch: 'node3',
      }),
      createNode('node3', 'end'),
    ]
    const edges = [
      createEdge('edge1', 'node1', 'node2'),
      createEdge('edge2', 'node2', 'node3'),
    ]

    const result = validateWorkflow(nodes, edges, false)

    // node1.input is valid (start node has 'input' output field)
    expect(result.valid).toBe(true)
  })
})

/* ─── Combined Validation Scenarios ─── */

describe('validateWorkflow - combined scenarios', () => {
  it('should report multiple errors at once', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'agent'), // missing agent_id
      createNode('node3', 'tool'), // missing tool_id
      createNode('node4', 'end'),
    ]
    const edges = [
      createEdge('edge1', 'node1', 'node2'),
      createEdge('edge2', 'node2', 'node3'),
      createEdge('edge3', 'node3', 'node4'),
    ]

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(false)
    // Should have multiple config errors (agent + tool)
    expect(result.errors.length).toBeGreaterThanOrEqual(2)
  })

  it('should pass complex but valid workflow', () => {
    const nodes = [
      createNode('node1', 'start'),
      createNode('node2', 'agent', {
        agent_id: 'agent_123',
        input_query: '{{input.query}}',
        input_prompt: '{{input.query}}',
      }),
      createNode('node3', 'tool', {
        tool_id: 'tool_456',
        params: { arg: '{{node2.response}}' },
      }),
      createNode('node4', 'gateway', {
        conditions: [
          { expression: '{{node3.result}} == "success"' },
        ],
        default_branch: 'node5',
      }),
      createNode('node5', 'end'),
    ]
    const edges = [
      createEdge('edge1', 'node1', 'node2'),
      createEdge('edge2', 'node2', 'node3'),
      createEdge('edge3', 'node3', 'node4'),
      createEdge('edge4', 'node4', 'node5'),
    ]

    const result = validateWorkflow(nodes, edges, false)

    expect(result.valid).toBe(true)
    expect(result.errors).toHaveLength(0)
  })
})
