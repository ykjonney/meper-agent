/** 工具创建/编辑弹窗（四步表单）——从 ToolMarketPage 拆出，行为不变。
 * 含表单子组件：CodeHelpPanel / ParamsTableEditor / OutputFieldsTree /
 * ParamListEditor / FormSection。AI 修改与保存后 AI 测试在此集成。 */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ChevronDown, Plus, Sparkles, Trash2, Wand2 } from 'lucide-react'
import { getErrorMessage } from '../../lib/api-client'
import { toast } from '../ui/toast'
import { confirmDialog } from '../ui/confirm'
import {
  userToolsApi,
  type UserToolDetail, type GeneratedToolDraft, type ToolDefinitionPayload,
} from '../../services/user-tools-api'
import {
  SOURCE_META, CODE_EXAMPLE, OPENAPI_EXAMPLE, OPENAPI_EXAMPLE_OUTPUT,
  PARAM_KEY_RE, PARAM_POS_LABEL, schemaToFields, fieldsToSchema,
  type ParamField, type ApiParam, type OutputField,
} from './tool-form-utils'
import { CodeEditor } from './CodeEditor'
import { AiGenerateDialog } from './AiGenerateDialog'
import { TestToolDialog } from './TestToolDialog'

function CodeHelpPanel({ onInsertExample, dark }: {
  onInsertExample: () => void; dark: boolean;
}) {
  const [open, setOpen] = useState(false);
  const item = `flex gap-2 ${dark ? 'text-[#a1a1aa]' : 'text-slate-600'}`;
  return (
    <div className={`rounded-lg border text-[11px] leading-relaxed ${
      dark ? 'border-[#27272a] bg-[#121214]/60' : 'border-slate-200 bg-slate-50/70'
    }`}>
      <button onClick={() => setOpen(!open)}
        className={`flex w-full items-center gap-1 px-2.5 py-1.5 cursor-pointer font-semibold ${
          dark ? 'text-[#d4d4d8] hover:text-white' : 'text-slate-700 hover:text-slate-900'
        }`}>
        <ChevronDown size={12} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
        代码怎么写？查看格式要求与可用依赖
      </button>
      {open && (
        <div className={`px-3 pb-3 pt-0.5 space-y-1.5 border-t ${dark ? 'border-[#27272a]' : 'border-slate-200'}`}>
          <div className={item}><span className="text-blue-400 shrink-0">入口</span>
            定义 <code className="font-mono text-blue-300">def run(...)</code>，参数名与「③ 运行参数」一致，调用时按名传入。</div>
          <div className={item}><span className="text-amber-400 shrink-0">凭证</span>
            「④ 凭证参数」通过环境变量读取：token → <code className="font-mono text-amber-300">os.environ["USER_token"]</code>。敏感值加密存储，管理员统一配置。</div>
          <div className={item}><span className="text-emerald-500 shrink-0">返回</span>
            return 字符串或 dict / list（自动转 JSON）；抛出异常时错误信息会返回给 AI 便于重试。</div>
          <div className={item}><span className="text-purple-400 shrink-0">依赖</span>
            可使用 Python 标准库和一些常用库（如 requests、httpx、pandas、numpy 等）；部分依赖可能被禁止安装，保存时会有提示。</div>
          <button onClick={onInsertExample}
            className="flex items-center gap-1.5 mt-1 px-2 py-1 rounded text-[11px] text-blue-400 hover:text-blue-300 hover:bg-blue-500/10 cursor-pointer">
            <Wand2 size={12} />填入完整示例（天气查询）
          </button>
        </div>
      )}
    </div>
  );
}

/** openapi 参数表行：参数名 | 位置 | 说明 | 凭证 | 必填 —— 主流 HTTP 工具模型，
 * 参数声明一次，位置决定发送到哪；凭证行的值由管理员配置（加密）。 */
function ParamsTableEditor({ rows, onChange, inputCls, selectCls }: {
  rows: ApiParam[]; onChange: (rows: ApiParam[]) => void;
  inputCls: string; selectCls: string;
}) {
  const update = (i: number, patch: Partial<ApiParam>) =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-[1fr_84px_1.5fr_54px_54px_28px] gap-1.5 text-[10px] text-[#71717a] px-0.5">
        <span>参数名</span><span>位置</span><span>说明（给使用者/AI 看）</span>
        <span className="text-center">凭证</span><span className="text-center">必填</span><span />
      </div>
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[1fr_84px_1.5fr_54px_54px_28px] gap-1.5 items-center">
          <input value={r.name} onChange={(e) => update(i, { name: e.target.value })}
            placeholder={r.in === 'header' ? 'Authorization' : 'city'}
            className={`w-full font-mono ${inputCls}`} />
          <select value={r.in} onChange={(e) => update(i, { in: e.target.value as ApiParam['in'] })}
            className={`w-full cursor-pointer ${selectCls}`}>
            {(Object.keys(PARAM_POS_LABEL) as ApiParam['in'][]).map((pos) => (
              <option key={pos} value={pos}>{PARAM_POS_LABEL[pos]}</option>
            ))}
          </select>
          <input value={r.description} onChange={(e) => update(i, { description: e.target.value })}
            placeholder={r.credential ? '认证 Key，管理员配置' : '城市名，如 Beijing'}
            className={`w-full ${inputCls}`} />
          <label className="flex items-center justify-center cursor-pointer" title="凭证：值由管理员统一配置（加密存储），调用时自动带上">
            <input type="checkbox" checked={r.credential} onChange={(e) => update(i, { credential: e.target.checked })}
              className="w-3.5 h-3.5 accent-amber-500 cursor-pointer" />
          </label>
          <label className="flex items-center justify-center cursor-pointer" title={r.credential ? '凭证必须配置后才能开启工具' : '调用时该参数必须提供'}>
            <input type="checkbox" checked={r.required} disabled={r.credential}
              onChange={(e) => update(i, { required: e.target.checked })}
              className="w-3.5 h-3.5 accent-blue-600 cursor-pointer disabled:opacity-30" />
          </label>
          <button onClick={() => onChange(rows.filter((_, idx) => idx !== i))}
            className="p-1 rounded text-red-400/70 hover:text-red-400 cursor-pointer justify-self-center" title="删除此参数">
            <Trash2 size={13} />
          </button>
        </div>
      ))}
      <button onClick={() => onChange([...rows, { name: '', in: 'query', description: '', required: false, credential: false }])}
        className="flex items-center gap-1 px-2 py-1 rounded text-xs text-blue-400 hover:text-blue-300 cursor-pointer">
        <Plus size={13} />添加参数
      </button>
    </div>
  );
}

/** 返回结构编辑器（递归树）：字段名/类型/列表/说明；对象类型可声明子字段 */
function OutputFieldsTree({ fields, onChange, inputCls, selectCls, depth = 0 }: {
  fields: OutputField[];
  onChange: (fields: OutputField[]) => void;
  inputCls: string;
  selectCls: string;
  depth?: number;
}) {
  const update = (i: number, patch: Partial<OutputField>) =>
    onChange(fields.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  const row = (f: OutputField, i: number) => (
    <div key={i} className="space-y-1">
      <div className="grid grid-cols-[1fr_84px_44px_1.3fr_28px] gap-1.5 items-center">
        <input value={f.name} onChange={(e) => update(i, { name: e.target.value })}
          placeholder="status" className={`w-full font-mono ${inputCls}`} />
        <select value={f.type} onChange={(e) => {
          const type = e.target.value as OutputField['type'];
          update(i, { type, fields: type === 'object' ? (f.fields ?? [{ name: '', type: 'string', description: '' }]) : undefined });
        }}
          className={`w-full cursor-pointer ${selectCls}`}>
          <option value="string">文本</option>
          <option value="number">数字</option>
          <option value="boolean">布尔</option>
          <option value="object">对象</option>
        </select>
        <label className="flex items-center justify-center cursor-pointer" title="列表（下游 .0 下标取值）">
          <input type="checkbox" checked={!!f.is_list} onChange={(e) => update(i, { is_list: e.target.checked })}
            className="w-3.5 h-3.5 accent-blue-600 cursor-pointer" />
        </label>
        <input value={f.description} onChange={(e) => update(i, { description: e.target.value })}
          placeholder="处理状态，success / failed" className={`w-full ${inputCls}`} />
        <button onClick={() => onChange(fields.filter((_, idx) => idx !== i))}
          className="p-1 rounded text-red-400/70 hover:text-red-400 cursor-pointer justify-self-center" title="删除此字段">
          <Trash2 size={13} />
        </button>
      </div>
      {f.type === 'object' && (
        <div className="ml-5 pl-3 border-l border-[#27272a] space-y-1.5">
          <OutputFieldsTree fields={f.fields ?? []}
            onChange={(next) => update(i, { fields: next })}
            inputCls={inputCls} selectCls={selectCls} depth={depth + 1} />
        </div>
      )}
    </div>
  );
  return (
    <div className="space-y-1.5">
      {depth === 0 && fields.length > 0 && (
        <div className="grid grid-cols-[1fr_84px_44px_1.3fr_28px] gap-1.5 text-[10px] text-[#71717a] px-0.5">
          <span>字段名</span><span>类型</span><span className="text-center">列表</span><span>说明（调用方可见）</span><span />
        </div>
      )}
      {fields.map(row)}
      <button onClick={() => onChange([...fields, { name: '', type: 'string', description: '', is_list: false }])}
        className={`flex items-center gap-1 px-2 py-1 rounded text-xs text-blue-400 hover:text-blue-300 cursor-pointer ${depth > 0 ? 'pl-0' : ''}`}>
        <Plus size={13} />{depth > 0 ? '添加子字段' : '添加返回字段'}
      </button>
    </div>
  );
}

/** 参数列表编辑器（运行参数 / 凭证参数）——自动生成 JSON Schema */
function ParamListEditor({ fields, onChange, mode, inputCls, selectCls }: {  fields: ParamField[]; onChange: (fields: ParamField[]) => void;
  mode: 'llm' | 'user'; inputCls: string; selectCls: string;
}) {
  const update = (i: number, patch: Partial<ParamField>) =>
    onChange(fields.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  const label = mode === 'llm' ? '必填' : '敏感';
  const labelTitle = mode === 'llm'
    ? '调用时该参数必须提供'
    : '值会加密存储（admin 在工具上统一配置）';
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-[1fr_84px_1.4fr_52px_28px] gap-1.5 text-[10px] text-[#71717a] px-0.5">
        <span>参数名</span><span>类型</span><span>说明（给使用者/AI 看）</span><span className="text-center">{label}</span><span />
      </div>
      {fields.map((f, i) => (
        <div key={i} className="grid grid-cols-[1fr_84px_1.4fr_52px_28px] gap-1.5 items-center">
          <input value={f.key} onChange={(e) => update(i, { key: e.target.value })}
            placeholder={mode === 'llm' ? 'city' : 'token'}
            className={`w-full ${inputCls}`} />
          <select value={f.type} onChange={(e) => update(i, { type: e.target.value as ParamField['type'] })}
            className={`w-full cursor-pointer ${selectCls}`}>
            <option value="string">文本</option>
            <option value="number">数字</option>
            <option value="boolean">布尔</option>
            {mode === 'llm' && <option value="array">列表</option>}
          </select>
          <input value={f.description} onChange={(e) => update(i, { description: e.target.value })}
            placeholder={mode === 'llm' ? '要查询的城市名，如 Beijing' : '服务端签发的 API Key'}
            className={`w-full ${inputCls}`} />
          <label className="flex items-center justify-center cursor-pointer" title={labelTitle}>
            <input type="checkbox" checked={mode === 'llm' ? f.required : f.sensitive}
              onChange={(e) => update(i, mode === 'llm' ? { required: e.target.checked } : { sensitive: e.target.checked })}
              className="w-3.5 h-3.5 accent-blue-600 cursor-pointer" />
          </label>
          <button onClick={() => onChange(fields.filter((_, idx) => idx !== i))}
            className="p-1 rounded text-red-400/70 hover:text-red-400 cursor-pointer justify-self-center" title="删除此参数">
            <Trash2 size={13} />
          </button>
        </div>
      ))}
      <button onClick={() => onChange([...fields, { key: '', type: 'string', description: '', required: false, sensitive: false }])}
        className="flex items-center gap-1 px-2 py-1 rounded text-xs text-blue-400 hover:text-blue-300 cursor-pointer">
        <Plus size={13} />添加参数
      </button>
    </div>
  );
}

/** 分区标题（步骤式引导） */
function FormSection({ step, title, hint, dark, children }: {
  step: string; title: string; hint?: string; dark: boolean; children: ReactNode;
}) {
  return (
    <div className={`rounded-xl border p-4 space-y-3 ${
      dark ? 'border-[#27272a] bg-[#121214]/60' : 'border-slate-200 bg-slate-50/60'
    }`}>
      <div className="space-y-0.5">
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded-full bg-blue-600/20 text-blue-500 text-[11px] font-bold flex items-center justify-center shrink-0">{step}</span>
          <span className={`text-sm font-bold ${dark ? 'text-white' : 'text-slate-900'}`}>{title}</span>
        </div>
        {hint && <p className={`text-[11px] leading-relaxed pl-7 ${dark ? 'text-[#71717a]' : 'text-slate-500'}`}>{hint}</p>}
      </div>
      {children}
    </div>
  );
}

export function ToolEditModal({ theme, initial, draft, onClose, onSaved }: {
  theme: 'dark' | 'light';
  initial?: UserToolDetail;
  /** AI 生成草稿——挂载时一次性回填表单（用户检查/修改后正常保存） */
  draft?: GeneratedToolDraft | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!initial;

  // ── ① 基本信息 ──
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [source, setSource] = useState(initial?.source ?? 'openapi');

  // ── ② 调用方式 ──
  const ep = (initial?.endpoint ?? {}) as Record<string, unknown>;
  const [method, setMethod] = useState((ep.method as string) ?? 'GET');
  const [url, setUrl] = useState((ep.url as string) ?? '');
  const [apiParams, setApiParams] = useState<ApiParam[]>(
    (Array.isArray(ep.params) ? ep.params : []) as ApiParam[],
  );
  const [code, setCode] = useState(initial?.code ?? '');
  // 返回字段声明（output_schema：{type:'object', fields:[{name,type,is_list,description}]}）
  // ——给下游工作流精确引用 {{node.result.字段}}；与 agent response_schema 同构
  const initOutSchema = (initial?.output_schema ?? {}) as { type?: string; fields?: OutputField[] };
  const [outputFields, setOutputFields] = useState<OutputField[]>(
    Array.isArray(initOutSchema.fields) ? initOutSchema.fields : [],
  );

  // ── ③/④ 参数 ──
  const [llmFields, setLlmFields] = useState<ParamField[]>(schemaToFields(initial?.llm_args_schema));
  const [userFields, setUserFields] = useState<ParamField[]>(schemaToFields(initial?.user_args_schema));

  const [busy, setBusy] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [testDef, setTestDef] = useState<ToolDefinitionPayload | null>(null);
  /** 保存后询问进入的测试——测试对话框关闭时统一收尾关闭整个表单 */
  const [postSaveTest, setPostSaveTest] = useState(false);
  const credFields = source === 'code'
    ? userFields.filter((f) => f.key.trim()).map((f) => ({ key: f.key, sensitive: f.sensitive }))
    : apiParams.filter((r) => r.credential && r.name.trim()).map((r) => ({ key: r.name, sensitive: true }));

  // AI 修改的对话种子：以「已保存的工具定义」为首条 assistant 消息
  const aiSeed = useMemo(() => {
    if (!initial) return null;
    return {
      content: '已载入当前保存的工具定义（见下方草稿卡）。请直接告诉我想怎么修改。',
      draft: {
        name: initial.name,
        description: initial.description,
        source: initial.source,
        llm_args_schema: initial.llm_args_schema,
        user_args_schema: initial.user_args_schema,
        endpoint: initial.endpoint,
        code: initial.code,
        output_schema: initial.output_schema,
        tags: initial.tags,
      } as GeneratedToolDraft,
    };
  }, [initial]);

  /** 一键填入「天气查询」完整示例（基本信息 + 调用方式 + 运行参数 + 凭证参数） */
  const applyExample = () => {
    setName('weather-query');
    setDescription('查询指定城市的实时天气');
    setOutputFields(OPENAPI_EXAMPLE_OUTPUT.map((f) => ({ ...f })));
    setLlmFields([
      { key: 'city', type: 'string', description: '城市名，如 Beijing', required: true, sensitive: false },
      { key: 'unit', type: 'string', description: '温度单位：celsius（默认）或 fahrenheit', required: false, sensitive: false },
    ]);
    if (source === 'openapi') {
      setMethod(OPENAPI_EXAMPLE.method);
      setUrl(OPENAPI_EXAMPLE.url);
      setApiParams(OPENAPI_EXAMPLE.params.map((r) => ({ ...r })));
      setCode('');
      setUserFields([]);
      setLlmFields([]);
    } else {
      setCode(CODE_EXAMPLE);
      setUserFields([
        { key: 'api_key', type: 'string', description: '服务端签发的 API Key', required: true, sensitive: true },
      ]);
    }
    toast.success('已填入示例，按需修改');
  };

  /** AI 生成草稿回填四步表单——用户检查/修改后正常保存（治理链不变） */
  const applyDraft = (d: GeneratedToolDraft) => {
    setName(d.name ?? '');
    setDescription(d.description ?? '');
    // 编辑态 source 不可改（按钮 disabled），按当前 source 归一填法
    const nextSource =
      !isEdit && (d.source === 'code' || d.source === 'openapi') ? d.source : source;
    if (nextSource !== source) setSource(nextSource);

    const outSchema = (d.output_schema ?? {}) as { fields?: OutputField[] };
    setOutputFields(Array.isArray(outSchema.fields) ? outSchema.fields : []);

    if (nextSource === 'openapi') {
      const dep = (d.endpoint ?? {}) as { method?: string; url?: string; params?: ApiParam[] };
      setMethod((dep.method ?? 'GET').toUpperCase());
      setUrl(dep.url ?? '');
      setApiParams(Array.isArray(dep.params) ? dep.params : []);
      setCode('');
      setLlmFields([]);
      setUserFields([]);
    } else {
      setCode(d.code ?? '');
      setLlmFields(schemaToFields(d.llm_args_schema));
      setUserFields(schemaToFields(d.user_args_schema));
    }
    toast.success('AI 已生成草稿——请检查参数与代码，按需修改后保存');
  };

  // AI 生成草稿：表单挂载时一次性回填（弹窗条件渲染，每次打开重新初始化）
  useEffect(() => {
    if (draft) applyDraft(draft);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dark = theme === 'dark';
  // 控件基础样式（无 w-full——flex 行内按 w-full 抢占空间会把兄弟元素挤成 0 宽）
  const ctlBase = `px-2 py-1 rounded text-xs border outline-none ${
    dark
      ? 'bg-[#121214] border-[#27272a] text-white placeholder:text-[#52525b] focus:border-blue-600'
      : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-blue-500'
  }`;
  const inputCls = `w-full ${ctlBase}`;
  const monoInputCls = `${inputCls} font-mono`;
  const selectCls = `${inputCls} cursor-pointer px-1`;
  const methodCls = `w-24 shrink-0 py-1.5 font-mono cursor-pointer ${ctlBase}`;
  const chipCls = dark ? 'bg-[#27272a]' : 'bg-slate-100';
  const plainInputCls = dark
    ? 'w-full px-3 py-1.5 rounded-lg text-sm border outline-none bg-[#121214] border-[#27272a] text-white placeholder:text-[#52525b] focus:border-blue-600'
    : 'w-full px-3 py-1.5 rounded-lg text-sm border outline-none bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-blue-500';

  /** 当前表单状态 → 工具定义（保存与试跑共用同一构造，防两路漂移） */
  const buildDefinition = (): ToolDefinitionPayload => {
    let endpoint: Record<string, unknown> = {};
    if (source === 'openapi') {
      endpoint = {
        method: method.toUpperCase(), url: url.trim(),
        params: apiParams.map((r) => ({
          name: r.name.trim(), in: r.in,
          description: r.description.trim(),
          required: r.credential ? true : r.required,
          credential: r.credential,
        })),
      };
      // 提取响应字段已下线（返回结构声明 + {{node.result.字段}} 直接引用取代）；
      // 存量工具的 response_path / response_notes 透传保留，运行时继续生效
      if (typeof ep.response_path === 'string' && ep.response_path.trim()) {
        endpoint.response_path = ep.response_path.trim();
      }
      if (typeof ep.response_notes === 'string' && ep.response_notes.trim()) {
        endpoint.response_notes = ep.response_notes.trim();
      }
    }
    return {
      name: name.trim(), description: description.trim(), source,
      endpoint,
      code: source === 'code' ? code : '',
      // openapi 的 schema 由后端按②参数表生成；code 按③④参数表定义
      llm_args_schema: source === 'code' ? fieldsToSchema(llmFields, 'llm') : {},
      user_args_schema: source === 'code' ? fieldsToSchema(userFields, 'user') : {},
      output_schema: outputFields.length
        ? { type: 'object', fields: outputFields.map((f) => ({ ...f, name: f.name.trim() })) }
        : {},
    };
  };

  const handleSave = async () => {
    if (!name.trim()) { toast.error('请先给工具起个名字'); return; }
    if (source === 'openapi' && !url.trim()) { toast.error('请填写要调用的接口地址（URL）'); return; }
    if (source === 'code' && !code.trim()) { toast.error('请填写工具的 Python 代码'); return; }
    // 参数名校验（openapi 参数表 / code 的③④参数表共用规则）
    const fieldGroups: ReadonlyArray<readonly [string, Array<{ key?: string; name?: string }>]> = source === 'code'
      ? [['运行参数', llmFields], ['凭证参数', userFields]]
      : [['参数表', apiParams.map((r) => ({ key: r.name }))]];
    for (const [label, fields] of fieldGroups) {
      for (const f of fields) {
        if (!String(f.key ?? '').trim()) { toast.error(`${label}里有未命名的参数，请填写参数名或删除该行`); return; }
        if (!PARAM_KEY_RE.test(String(f.key).trim())) {
          toast.error(`${label}「${f.key}」的参数名只能用字母、数字、下划线，且不能以数字开头`);
          return;
        }
      }
    }

    setBusy(true);
    try {
      const body = buildDefinition();
      if (isEdit) await userToolsApi.update(initial!.id, body);
      else await userToolsApi.create(body);
      // 保存成功 → 询问是否立即 AI 测试（方案 A：轻量二元确认，
      // 跳过即按原路收尾；测试对话框关闭时统一 onSaved）
      const wantTest = await confirmDialog({
        title: '保存成功',
        description: '是否立即进行 AI 测试？生成用例并试跑验证后，再提交发布更有把握。',
        okText: '开始测试',
        cancelText: '跳过',
      });
      if (wantTest) {
        setPostSaveTest(true);
        setTestDef(buildDefinition());
      } else {
        onSaved();
      }
    } catch (e) {
      toast.error(getErrorMessage(e, isEdit ? '保存失败' : '创建失败'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6" onClick={busy ? undefined : onClose}>
      <div className={`w-full max-w-2xl max-h-[85vh] flex flex-col rounded-2xl border overflow-hidden ${
          dark ? 'border-[#27272a] bg-[#18181b] text-[#fafafa]' : 'border-slate-200 bg-white text-slate-900'
        }`}
        onClick={(e) => e.stopPropagation()}>
        {/* 头部固定：滚动时标题与关闭按钮始终可见 */}
        <div className={`flex items-start justify-between shrink-0 px-6 pt-6 pb-3 border-b ${
          dark ? 'border-[#27272a]' : 'border-slate-200'
        }`}>
          <div>
            <h3 className="text-base font-bold flex items-center gap-2">
              {isEdit ? '编辑工具' : '创建工具'}
              {isEdit && (
                <button onClick={() => setAiOpen(true)}
                  title="AI 修改：以当前保存的工具定义为起点对话式打磨，应用后回填本表单"
                  className={`flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium cursor-pointer transition ${
                    dark
                      ? 'border border-blue-500/40 text-blue-400 hover:bg-blue-500/10'
                      : 'border border-blue-300 text-blue-600 hover:bg-blue-50'
                  }`}>
                  <Sparkles size={12} />AI 修改
                </button>
              )}
            </h3>
            <p className={`text-[11px] mt-0.5 ${dark ? 'text-[#71717a]' : 'text-slate-500'}`}>
              创建后提交发布，经管理员审查、开启后才能被 Agent 与工作流使用。
            </p>
          </div>
          <button onClick={onClose} className={`cursor-pointer hover:opacity-70 ${dark ? 'text-[#a1a1aa]' : 'text-slate-400'}`}>✕</button>
        </div>

        {/* 内容区滚动 */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">

        {/* ① 基本信息 */}
        <FormSection step="1" title="基本信息" dark={dark}
          hint="给工具起个名字、说清楚它做什么。">
          <div className="grid grid-cols-1 gap-3 pl-7">
            <div className="flex gap-2">
              {(['openapi', 'code'] as const).map((s) => {
                const meta = SOURCE_META[s];
                const desc = s === 'openapi' ? '封装一个 HTTP 接口' : '运行一段 Python 代码';
                return (
                  <button key={s} disabled={isEdit} onClick={() => setSource(s)}
                    className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs border cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed transition ${
                      source === s
                        ? 'bg-blue-600/20 border-blue-600/60 text-blue-500'
                        : dark
                          ? 'border-[#27272a] bg-transparent text-[#a1a1aa] hover:text-white'
                          : 'border-slate-200 bg-transparent text-slate-500 hover:text-slate-900'
                    }`}>
                    <meta.icon size={13} className={meta.cls} />
                    <span className="font-semibold">{meta.label}</span>
                    <span className={`text-[10px] ${dark ? 'text-[#71717a]' : 'text-slate-400'}`}>{desc}</span>
                  </button>
                );
              })}
            </div>
            <label className="space-y-1 block">
              <span className={`text-xs ${dark ? 'text-[#a1a1aa]' : 'text-slate-500'}`}>工具名称（字母数字开头，可含 - _，组织内唯一）</span>
              <input value={name} onChange={(e) => setName(e.target.value)} className={plainInputCls} placeholder="weather-query" />
            </label>
            <label className="space-y-1 block">
              <span className={`text-xs ${dark ? 'text-[#a1a1aa]' : 'text-slate-500'}`}>工具描述</span>
              <input value={description} onChange={(e) => setDescription(e.target.value)} className={plainInputCls} placeholder="查询指定城市的实时天气" />
            </label>
          </div>
        </FormSection>

        {/* ② 调用方式 */}
        {source === 'openapi' ? (
          <FormSection step="2" title="要调用的接口" dark={dark}
            hint="填一个 HTTP 接口 + 参数表。参数写在哪就发到哪（Query / 请求头 / URL 路径 / Body）：调用时 AI 填值，勾「凭证」的由管理员配置真值（加密存储）。">
            <div className="space-y-3 pl-7">
              <div className="flex gap-2">
                <select value={method} onChange={(e) => setMethod(e.target.value)}
                  className={methodCls}>
                  {['GET', 'POST', 'PUT', 'DELETE'].map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
                <input value={url} onChange={(e) => setUrl(e.target.value)} className={`flex-1 min-w-0 ${monoInputCls}`}
                  placeholder="https://api.example.com/v1/weather（路径参数写 {city}）" />
              </div>
              <button onClick={applyExample}
                className="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] text-blue-400 hover:text-blue-300 hover:bg-blue-500/10 cursor-pointer">
                <Wand2 size={12} />填入完整示例（天气查询）
              </button>

              <div className="space-y-1.5">
                <span className={`text-xs ${dark ? 'text-[#a1a1aa]' : 'text-slate-500'}`}>参数表——写一次，按位置发送</span>
                <ParamsTableEditor rows={apiParams} onChange={setApiParams}
                  inputCls={inputCls} selectCls={selectCls} />
              </div>
              <div className="space-y-1.5">
                <span className={`text-xs ${dark ? 'text-[#a1a1aa]' : 'text-slate-500'}`}>返回结构（可选）——声明后下游节点可直接调用 {'{{node.result.字段}}'}（对象类型可声明子字段）</span>
                <OutputFieldsTree fields={outputFields} onChange={setOutputFields}
                  inputCls={inputCls} selectCls={selectCls} />
              </div>
            </div>
          </FormSection>
        ) : (
          <FormSection step="2" title="Python 代码" dark={dark}
            hint="在隔离环境中安全运行。定义一个 run 函数（入参即「③ 运行参数」），返回字符串或可 JSON 化的结果。">
            <div className="space-y-2 pl-7">
              <CodeHelpPanel dark={dark} onInsertExample={applyExample} />
              <CodeEditor value={code} onChange={setCode}
                placeholder={'import math\n\ndef run(radius: str) -> str:\n    """计算圆的面积"""\n    return str(math.pi * float(radius) ** 2)'} />
              <div className="space-y-1.5">
                <span className={`text-xs ${dark ? 'text-[#a1a1aa]' : 'text-slate-500'}`}>返回结构（可选）——声明后下游节点可直接调用 {'{{node.result.字段}}'}（对象类型可声明子字段）</span>
                <OutputFieldsTree fields={outputFields} onChange={setOutputFields}
                  inputCls={inputCls} selectCls={selectCls} />
              </div>
            </div>
          </FormSection>
        )}

        {/* ③ 运行参数——仅 code 模式（openapi 的参数在②参数表里） */}
        {source === 'code' && (
          <FormSection step="3" title="运行参数" dark={dark}
            hint="每次调用时动态变化的信息（如城市名、搜索词），由 AI 或工作流节点在调用时填写。">
            <div className="pl-7">
              <ParamListEditor fields={llmFields} onChange={setLlmFields} mode="llm"
                inputCls={inputCls} selectCls={selectCls} />
            </div>
          </FormSection>
        )}

        {/* ④ 凭证参数——仅 code 模式（openapi 凭证勾在②参数表里） */}
        {source === 'code' && (
          <FormSection step="4" title="凭证参数" dark={dark}
            hint="固定不变的配置或凭证（如 API Key）。发布后由管理员在工具上统一配置（勾选「敏感」的值加密存储），所有使用点共用。代码中通过 USER_ 前缀环境变量读取。">
            <div className="pl-7">
              <ParamListEditor fields={userFields} onChange={setUserFields} mode="user"
                inputCls={inputCls} selectCls={selectCls} />
            </div>
          </FormSection>
        )}
        </div>

        {/* 底部按钮固定 */}
        <div className={`flex justify-end gap-2 shrink-0 px-6 py-4 border-t ${
          dark ? 'border-[#27272a]' : 'border-slate-200'
        }`}>
          <button onClick={onClose} disabled={busy}
            className={`px-3 py-1.5 rounded-lg text-sm cursor-pointer ${dark ? 'text-[#a1a1aa] hover:text-white' : 'text-slate-500 hover:text-slate-900'}`}>取消</button>
          <button onClick={handleSave} disabled={busy}
            className="px-4 py-1.5 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white cursor-pointer disabled:opacity-50">
            {busy ? '保存中…' : isEdit ? '保存' : '创建'}
          </button>
        </div>
      </div>

      {/* AI 修改：以已保存定义为起点的对话式修订，应用后回填本表单 */}
      {aiOpen && (
        <AiGenerateDialog
          dark={dark}
          seed={aiSeed}
          applyLabel="应用修改"
          onClose={() => setAiOpen(false)}
          onApply={(d) => { applyDraft(d); setAiOpen(false); }}
        />
      )}

      {/* AI 测试：保存后询问进入（或后续入口）；关闭时若为保存后测试则统一收尾 */}
      {testDef && (
        <TestToolDialog
          dark={dark}
          definition={testDef}
          credFields={credFields}
          onClose={() => {
            setTestDef(null);
            if (postSaveTest) {
              setPostSaveTest(false);
              onSaved();
            }
          }}
        />
      )}
    </div>
  );
}
