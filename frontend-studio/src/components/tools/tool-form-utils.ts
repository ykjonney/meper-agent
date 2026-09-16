/** 工具表单共享类型与工具函数——创建/编辑表单、示例、schema 互转
 * （ToolEditModal 与 ToolMarketPage 卡片共用，单一事实源防漂移）。 */
import { Globe, Code2 } from 'lucide-react'

export const SOURCE_META: Record<string, { label: string; icon: typeof Globe; cls: string }> = {
  openapi: { label: 'API', icon: Globe, cls: 'text-blue-400' },
  code: { label: 'Code', icon: Code2, cls: 'text-emerald-500' },
};

export interface ParamField {
  key: string;
  type: 'string' | 'number' | 'boolean' | 'array';
  description: string;
  /** 运行参数：调用时必填 */
  required: boolean;
  /** 凭证参数：值加密存储 */
  sensitive: boolean;
}

export const PARAM_KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

export function schemaToFields(schema?: Record<string, unknown>): ParamField[] {
  const props = (schema?.properties ?? {}) as Record<string, Record<string, unknown>>;
  const required = new Set(((schema?.required as string[]) ?? []));
  return Object.entries(props).map(([key, p]) => ({
    key,
    type: ((p.type as string) in { string: 1, number: 1, boolean: 1, array: 1 } ? p.type : 'string') as ParamField['type'],
    description: (p.description as string) ?? '',
    required: required.has(key),
    sensitive: !!p.sensitive,
  }));
}

export function fieldsToSchema(fields: ParamField[], mode: 'llm' | 'user'): Record<string, unknown> {
  const props: Record<string, unknown> = {};
  const required: string[] = [];
  for (const f of fields) {
    if (!f.key.trim()) continue;
    const prop: Record<string, unknown> = { type: f.type, description: f.description };
    if (f.type === 'array') prop.items = { type: 'string' }; // 元素为文本（file_id/路径列表等）
    if (mode === 'user' && f.sensitive) prop.sensitive = true;
    props[f.key.trim()] = prop;
    if (f.required) required.push(f.key.trim());
  }
  if (!Object.keys(props).length) return {};
  return { type: 'object', properties: props, required };
}


export interface ApiParam {
  name: string;
  in: 'query' | 'header' | 'path' | 'body';
  description: string;
  required: boolean;
  credential: boolean;
}

export const PARAM_POS_LABEL: Record<ApiParam['in'], string> = {
  query: 'Query', header: '请求头', path: '路径', body: 'Body',
};

export interface OutputField {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'object';
  description: string;
  is_list?: boolean;
  fields?: OutputField[];
}

export const CODE_EXAMPLE = `import os
import requests


def run(city: str, unit: str = "celsius") -> dict:
    """查询城市天气。city / unit 与「运行参数」一一对应。"""
    resp = requests.get(
        "https://api.example.com/v1/weather",
        params={"city": city, "unit": unit},
        headers={"Authorization": "Bearer " + os.environ["USER_api_key"]},  # 凭证参数 api_key（敏感）
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return {"city": city, "temperature": data["temperature"], "unit": unit}
`;

// openapi 版——URL + 参数表（位置定发送；凭证行由管理员配置）
export const OPENAPI_EXAMPLE = {
  method: 'GET',
  url: 'https://api.example.com/v1/weather',
  params: [
    { name: 'city', in: 'query', description: '城市名，如 Beijing', required: true, credential: false },
    { name: 'unit', in: 'query', description: '温度单位：celsius（默认）或 fahrenheit', required: false, credential: false },
    { name: 'Authorization', in: 'header', description: '认证，格式 Bearer <API Key>', required: true, credential: true },
  ] as ApiParam[],
};
export const OPENAPI_EXAMPLE_OUTPUT: OutputField[] = [
  { name: 'status', type: 'string', description: '处理状态：success / failed', is_list: false },
  { name: 'city', type: 'string', description: '城市名', is_list: false },
  { name: 'temperature', type: 'number', description: '温度值', is_list: false },
];
