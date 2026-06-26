/**
 * 节点类型配置常量 — 每种节点在编辑器中的展示信息。
 *
 * lucide-react 版本（替换原 @ant-design/icons）。
 */
import React from 'react'
import {
  PlayCircle,
  StopCircle,
  Workflow,
  Wrench,
  GitBranch,
  Split,
  UserCheck,
} from 'lucide-react'

export interface NodeTypeConfig {
  label: string
  color: string
  bg: string
  icon: React.ReactNode
  description: string
}

const ICON_PROPS = { size: 14, strokeWidth: 2 }

export const NODE_TYPE_CONFIGS: Record<string, NodeTypeConfig> = {
  start: {
    label: '开始',
    color: '#10B981',
    bg: '#D1FAE5',
    icon: React.createElement(PlayCircle, ICON_PROPS),
    description: '初始化变量池并映射输入参数',
  },
  end: {
    label: '结束',
    color: '#EF4444',
    bg: '#FEE2E2',
    icon: React.createElement(StopCircle, ICON_PROPS),
    description: '汇总输出并标记工作流完成',
  },
  agent: {
    label: 'Agent',
    color: '#3B82F6',
    bg: '#DBEAFE',
    icon: React.createElement(Workflow, ICON_PROPS),
    description: '调用 Agent 进行推理/行动',
  },
  tool: {
    label: '工具',
    color: '#F59E0B',
    bg: '#FEF3C7',
    icon: React.createElement(Wrench, ICON_PROPS),
    description: '调用已注册的工具或 Skill',
  },
  gateway: {
    label: '网关',
    color: '#8B5CF6',
    bg: '#EDE9FE',
    icon: React.createElement(GitBranch, ICON_PROPS),
    description: '评估条件并选择分支路径',
  },
  parallel: {
    label: '并行',
    color: '#06B6D4',
    bg: '#CFFAFE',
    icon: React.createElement(Split, ICON_PROPS),
    description: '并行执行多个分支',
  },
  human: {
    label: '人工审批',
    color: '#F97316',
    bg: '#FFF7ED',
    icon: React.createElement(UserCheck, ICON_PROPS),
    description: '等待人工审批后继续',
  },
}

/** 所有节点类型 key 列表（用于 palette 排序） */
export const NODE_TYPE_KEYS = Object.keys(NODE_TYPE_CONFIGS)
