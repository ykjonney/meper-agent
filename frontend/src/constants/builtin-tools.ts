/**
 * Built-in tool definitions — single source of truth for tool name,
 * display label, and description.
 *
 * Used by ToolsPage (builtin grid) and ToolSelector (checkbox group).
 */

export interface BuiltinToolDef {
  /** Machine name matching the backend registry */
  name: string
  /** Human-readable label */
  label: string
  /** Short one-line description */
  description: string
}

export const BUILTIN_TOOLS: readonly BuiltinToolDef[] = [
  { name: 'bash', label: 'Bash', description: '执行 Shell 命令' },
  { name: 'read', label: 'Read', description: '读取文件内容' },
  { name: 'write', label: 'Write', description: '写入文件内容' },
] as const
