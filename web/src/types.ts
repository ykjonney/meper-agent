export interface Agent {
  id: string;
  name: string;
  description: string;
  status: 'published' | 'draft' | 'deprecated' | 'archived';
  type: 'conversational' | 'service' | 'hybrid';
  tags: string[];
  systemPrompt: string;
  persona: {
    role: string;
    tone: string;
    welcomeMessage: string;
    constraints: string[];
  };
  models: {
    model: string;
    priority: number;
    maxTokens: number;
    temperature: number;
    enabled: boolean;
  }[];
  skills: string[]; // references of Skill.id
  mcpServers: string[]; // references of MCPServer.id
  flows: string[]; // references of Flow.id — agent 可感知并执行的流水线
  visibility: 'me' | 'org' | 'public';
  version: string;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  type: 'Function';
  category: 'Built-in' | 'Custom';
  version: string;
  tags: string[];
  schema: string; // JSON schema structure as text
  testParams: string; // prefilled arguments JSON text
  mockOutput: string; // predefined return response
}

export interface MCPServer {
  id: string;
  name: string;
  description: string;
  status: 'connected' | 'connecting' | 'disconnected';
  connectionType: 'STDIO' | 'SSE' | 'Streamable HTTP';
  lastConnected: string;
  error?: string;
  toolsCount: number;
  resourcesCount: number;
  promptsCount: number;
  tools: {
    name: string;
    description: string;
    schema: string;
  }[];
  config: {
    command?: string;
    args?: string[];
    env?: { key: string; value: string }[];
    url?: string;
    headers?: { key: string; value: string }[];
    token?: string;
    timeout?: number;
    reconnect?: boolean;
    maxRetries?: number;
  };
  logs: {
    time: string;
    fromStatus: string;
    toStatus: string;
    message: string;
  }[];
}

export interface SubTask {
  id: string;
  title: string;
  status: 'completed' | 'running' | 'pending';
  progress: number;
}

export interface TimelineEntry {
  id: string;
  time: string;
  status: string;
  message: string;
}

export interface PresetNode {
  id: string;
  name: string;
  description: string;
  agentId: string; // Bound agent
  preFilledInput: string; // Custom input configuration JSON/text
}

export interface FlowNodeRef {
  nodeId: string; // ID of the PresetNode used
  overrideInput?: string; // Optional custom inputs for this workflow step
}

export interface Flow {
  id: string;
  name: string;
  description: string;
  nodes: FlowNodeRef[]; // Sequence of node operations
  createdAt: string;
  lastTriggeredAt?: string;
}

export interface Task {
  id: string;
  title: string;
  description: string;
  status: 'created' | 'planned' | 'running' | 'review' | 'paused' | 'completed' | 'failed' | 'cancelled';
  priority: 'low' | 'medium' | 'high' | 'urgent';
  agentId: string;
  progress: number;
  tags: string[];
  input: string; // stringified JSON
  output?: string; // stringified JSON
  maxRetries: number;
  timeout: number;
  createdAt: string;
  updatedAt: string;
  subtasks: SubTask[];
  timeline: TimelineEntry[];
  sourceChatId?: string;
  flowId?: string; // If triggered by flow, track flow reference
  currentStepIndex?: number; // Active step index (0-based) for flow execution
}

export interface ToolCall {
  id: string;
  name: string;
  args: string; // stringified JSON arguments
  status: 'running' | 'success' | 'failed';
  result?: string;
  error?: string;
  duration?: number;
}

export interface TaskCardData {
  taskId: string;
  title: string;
  priority: 'low' | 'medium' | 'high' | 'urgent';
  status: Task['status'];
  progress: number;
  subtasks?: SubTask[];
  resultSummary?: string;
}

export interface Message {
  id: string;
  sender: 'user' | 'agent' | 'system';
  text: string;
  timestamp: string;
  toolCalls?: ToolCall[];
  taskCard?: TaskCardData;
  suggestionCard?: {
    title: string;
    stepsCount: number;
    eta: string;
  };
  delegationTip?: {
    taskId: string;
    progress: number;
  };
}

export interface User {
  id: string;
  username: string;
  email: string;
  password: string;
  phone?: string;
  department?: string;
  bio?: string;
  status: 'active' | 'inactive' | 'locked';
  roleIds: string[];
  createdAt: string;
  lastLoginAt?: string;
}

export interface Role {
  id: string;
  name: string;
  code: string;
  description: string;
  permissionIds: string[];
  isSystem: boolean;
  createdAt: string;
}

export interface Permission {
  id: string;
  module: string;
  action: string;
  label: string;
  description: string;
  enabled: boolean;
}

export interface Chat {
  id: string;
  agentId: string;
  title: string;
  updatedAt: string;
  messages: Message[];
}
