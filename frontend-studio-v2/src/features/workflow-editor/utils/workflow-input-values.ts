/**
 * 工作流输入参数的值推导 / 校验 / 强转 —— 供执行参数弹窗与定时任务弹窗共用。
 *
 * 开始节点声明的输入变量（VariableDefinition[]）在不同入口需要：
 *  - 推导初始值（按类型 + constraints.default_value）
 *  - 必填校验
 *  - 提交时按类型强转（text/number/boolean/json/select/file）
 * 这里把三段纯逻辑集中，UI 层只管渲染与事件。
 */
import type { VariableDefinition } from './variable-types'

/** 强转结果：error 非 null 表示失败（如 json 解析失败），此时 values 为空对象。 */
export interface CoerceResult {
  values: Record<string, unknown>
  error: string | null
}

/**
 * 按 variables 推导初始值（未填）。
 * - boolean：默认 false（除非 constraints.default_value 是布尔）
 * - select/file + multiple：默认 []
 * - select 单选 / file 单选：默认 ''
 * - number：默认值为字符串形态（输入框受控），无则 ''
 * - text/json：默认值字符串化，无则 ''
 */
export function buildDefaultValues(
  variables: VariableDefinition[],
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const v of variables) {
    const dv = v.constraints?.default_value
    const multiple = !!v.constraints?.multiple
    let value: unknown
    switch (v.type) {
      case 'boolean':
        value = typeof dv === 'boolean' ? dv : false
        break
      case 'select':
        value = multiple ? (Array.isArray(dv) ? dv : []) : typeof dv === 'string' ? dv : ''
        break
      case 'file':
        value = multiple ? [] : ''
        break
      case 'number':
        value = dv !== null && dv !== undefined && dv !== '' ? String(dv) : ''
        break
      default:
        value =
          typeof dv === 'string'
            ? dv
            : dv !== null && dv !== undefined
              ? String(dv)
              : ''
    }
    out[v.name] = value
  }
  return out
}

/**
 * 必填校验：返回未满足必填条件的变量名集合。
 * - file / select(multiple)：需要非空数组
 * - boolean：总有值，视为满足
 * - 其余：去掉空串/空白后判空
 */
export function findMissingRequired(
  variables: VariableDefinition[],
  values: Record<string, unknown>,
): string[] {
  const missing: string[] = []
  for (const v of variables) {
    if (!v.required) continue
    const val = values[v.name]
    if (v.type === 'file' || (v.type === 'select' && v.constraints?.multiple)) {
      if (!Array.isArray(val) || val.length === 0) missing.push(v.name)
    } else if (v.type === 'boolean') {
      // boolean 总有值，跳过
    } else {
      if (val === null || val === undefined || String(val).trim() === '') missing.push(v.name)
    }
  }
  return missing
}

/**
 * 提交时按类型强转 raw 值，组装为后端期望的 input 对象。
 * - 空值（''/null/undefined/空数组）一律跳过，由后端用 default/None。
 * - number：转 Number，NaN 跳过。
 * - boolean：!!val。
 * - json：字符串则 JSON.parse（失败返回 error），非字符串原样。
 * - select/file：multiple 取数组，单选取标量。
 * - text：原样字符串。
 */
export function coerceValues(
  variables: VariableDefinition[],
  raw: Record<string, unknown>,
): CoerceResult {
  const out: Record<string, unknown> = {}
  for (const v of variables) {
    const val = raw[v.name]
    switch (v.type) {
      case 'number': {
        if (val === '' || val === null || val === undefined) continue
        const n = Number(val)
        if (Number.isNaN(n)) continue
        out[v.name] = n
        break
      }
      case 'boolean':
        out[v.name] = !!val
        break
      case 'json': {
        if (typeof val === 'string' && val.trim() === '') continue
        try {
          out[v.name] = typeof val === 'string' ? JSON.parse(val) : val
        } catch {
          return { values: {}, error: `变量 ${v.label || v.name} 的 JSON 解析失败` }
        }
        break
      }
      case 'select': {
        if (v.constraints?.multiple) {
          const arr = (val as string[]) ?? []
          if (arr.length === 0) continue
          out[v.name] = arr
        } else {
          if (val === '' || val === null || val === undefined) continue
          out[v.name] = val
        }
        break
      }
      case 'file': {
        if (v.constraints?.multiple) {
          const arr = (val as string[]) ?? []
          if (arr.length === 0) continue
          out[v.name] = arr
        } else {
          if (!val) continue
          out[v.name] = val
        }
        break
      }
      default: {
        // text
        if (val === '' || val === null || val === undefined) continue
        out[v.name] = val
      }
    }
  }
  return { values: out, error: null }
}
