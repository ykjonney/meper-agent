/**
 * Parameter utilities — convert ToolParam[] to JSON Schema.
 */
import type { ToolParam } from './param-editor'

/**
 * Convert ToolParam[] to JSON Schema (for backend storage).
 */
export function paramsToSchema(params: ToolParam[]): Record<string, unknown> {
  const properties: Record<string, unknown> = {}
  const required: string[] = []
  for (const p of params) {
    properties[p.name] = {
      type: p.type,
      ...(p.description ? { description: p.description } : {}),
    }
    if (p.required) required.push(p.name)
  }
  return {
    type: 'object',
    properties,
    ...(required.length > 0 ? { required } : {}),
  }
}
