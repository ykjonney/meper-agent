/** 工具工坊（tool-forge agent，流式对话）——harness 小型 agent 驱动：
 * 出草稿 → 自动测试 → 失败自我修订 → 通过自动保存；凭证缺口经
 * ask_clarification interrupt 弹卡交互，作答/跳过后 resume 续跑。用户全程
 * 无需手动保存；edit 模式的已保存定义由后端注入对话。手动精修走卡片
 * 「编辑」进 ToolEditModal，与本对话框无关。 */
import { useEffect, useRef, useState } from 'react'
import { Loader2, Play, Send, Sparkles } from 'lucide-react'
import { getErrorMessage } from '../../lib/api-client'
import { parseSSEStream } from '../../lib/sse-parser'
import { toast } from '../ui/toast'
import { Markdown } from '../Markdown'
import { useActiveModels } from '../../hooks/use-active-models'
import type { StreamEvent } from '../../services/agent-api'
import {
  forgeApi,
  type ForgeDoneEvent,
  type GeneratedToolDraft,
} from '../../services/user-tools-api'
import { SOURCE_META } from './tool-form-utils'

/** 工具调用的中文标签（卡片展示用） */
const TOOL_LABEL: Record<string, string> = {
  submit_definition: '提交草稿',
  make_test_cases: '生成测试用例',
  run_test: '试跑',
  save_tool: '保存工具',
  ask_clarification: '询问用户',
}

type Msg =
  | { kind: 'user'; content: string }
  | { kind: 'assistant'; content: string }
  | { kind: 'tool'; name: string; status: 'run' | 'ok' | 'error'; detail: string }

/** interrupt 卡（ask_clarification）：fields 非空渲染结构化表单（凭证等） */
interface InterruptCard {
  question: string
  context?: string | null
  options?: string[] | null
  fields?: Array<{ name?: string; label?: string; field_type?: string } | Record<string, unknown>>
}

export function AiGenerateDialog({ dark, onClose, mode = 'create', toolId = '', toolInfo, onSavedTool }: {
  dark: boolean;
  onClose: () => void;
  /** create=新建（save_tool=create）| edit=修改已有（后端注入已保存定义，save=update） */
  mode?: 'create' | 'edit';
  toolId?: string;
  /** edit 模式：当前工具信息（头部展示，让用户知道在改哪个工具） */
  toolInfo?: { name: string; source?: string; description?: string };
  /** save_tool 成功后回调（刷新列表等；agent 迭代可多次触发） */
  onSavedTool?: () => void;
}) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [streamText, setStreamText] = useState('');
  const [input, setInput] = useState('');
  const [sourceSel, setSourceSel] = useState('');
  const [apiUrl, setApiUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [forgeId, setForgeId] = useState('');
  const [latestDraft, setLatestDraft] = useState<GeneratedToolDraft | null>(null);
  const [savedId, setSavedId] = useState('');
  const [interrupt, setInterrupt] = useState<InterruptCard | null>(null);
  const [fieldAnswers, setFieldAnswers] = useState<Record<string, string>>({});
  const bottomRef = useRef<HTMLDivElement>(null);

  const { activeModels, modelId, setModelId } = useActiveModels();
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamText, busy, interrupt]);

  /** 消费一轮 SSE：事件分发（文本流/工具卡/interrupt/done 帧） */
  const consume = async (res: Response) => {
    for await (const evt of parseSSEStream(res)) {
      const e = evt as StreamEvent | ForgeDoneEvent;
      if (!('type' in e)) {
        // done 帧（工坊扩展：附草稿与保存态）
        const done = e as ForgeDoneEvent;
        if (done.draft) setLatestDraft(done.draft);
        if (done.saved_tool_id && done.saved_tool_id !== savedId) {
          setSavedId(done.saved_tool_id);
          toast.success('工具已保存');
          onSavedTool?.();
        }
        continue;
      }
      switch (e.type) {
        case 'text_delta':
          setStreamText((t) => t + e.content);
          break;
        case 'text': {
          // 完整文本块——落为一条 assistant 消息（delta 期间已流式展示）
          if (e.content) {
            setMessages((prev) => [...prev, { kind: 'assistant', content: e.content }]);
          }
          setStreamText('');
          break;
        }
        case 'tool_call':
          setMessages((prev) => [...prev, {
            kind: 'tool', name: e.tool_name, status: 'run', detail: '',
          }]);
          break;
        case 'tool_result': {
          // 配对最后一个同名 run 卡；结果摘要截断展示
          const ok = e.status !== 'error';
          const detail = (e.content || '').slice(0, 500);
          setMessages((prev) => {
            const next = [...prev];
            for (let i = next.length - 1; i >= 0; i--) {
              const m = next[i];
              if (m.kind === 'tool' && m.name === e.tool_name && m.status === 'run') {
                next[i] = { ...m, status: ok ? 'ok' : 'error', detail };
                break;
              }
            }
            return next;
          });
          break;
        }
        case 'interrupt':
          setInterrupt({
            question: e.question,
            context: e.context ?? null,
            options: e.options ?? null,
            fields: e.fields ?? undefined,
          });
          break;
        case 'error':
          toast.error(e.content || '执行出错');
          break;
        default:
          break; // thinking 等事件不展示
      }
    }
  };

  const send = async (text?: string) => {
    const raw = (text ?? input).trim();
    if (!raw || busy) return;
    // 工具类型/接口地址提示（选填）拼进首条消息
    const fullText = apiUrl.trim() && sourceSel === 'openapi'
      ? `${raw}\n（工具要调用的接口地址：${apiUrl.trim()}）`
      : sourceSel && mode === 'create'
        ? `${raw}\n（希望用 ${sourceSel === 'code' ? 'Python 代码' : 'HTTP 接口封装'} 实现）`
        : raw;
    setMessages((prev) => [...prev, { kind: 'user', content: raw }]);
    setInput('');
    setInterrupt(null);
    setFieldAnswers({});
    setBusy(true);
    try {
      const res = await forgeApi.stream({
        message: fullText, model_id: modelId, mode, tool_id: toolId, forge_id: forgeId,
      });
      if (!forgeId) {
        const id = res.headers.get('X-Forge-Id') ?? '';
        if (id) setForgeId(id);
      }
      await consume(res);
    } catch (e) {
      toast.error(getErrorMessage(e, '生成失败，请重试'));
    } finally {
      setBusy(false);
    }
  };

  /** interrupt 答复：fields 表单 → dict；无 fields → 文本（也可直接在输入框回复） */
  const answer = async (value: Record<string, unknown> | string) => {
    if (busy || !forgeId) return;
    const label = typeof value === 'string' ? value : Object.values(value).join('、');
    setMessages((prev) => [...prev, { kind: 'user', content: `（答复）${label}`.slice(0, 120) }]);
    setInterrupt(null);
    setFieldAnswers({});
    setBusy(true);
    try {
      await consume(await forgeApi.resume(forgeId, value));
    } catch (e) {
      toast.error(getErrorMessage(e, '恢复失败，请重试'));
    } finally {
      setBusy(false);
    }
  };

  const muted = dark ? 'text-[#71717a]' : 'text-slate-500';
  const ctlCls = `px-2 py-1.5 rounded text-xs border outline-none ${
    dark
      ? 'bg-[#121214] border-[#27272a] text-white placeholder:text-[#52525b] focus:border-blue-600'
      : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-blue-500'
  }`;
  const selectCls = `${ctlCls} cursor-pointer`;

  const fieldList = (interrupt?.fields ?? []) as Array<{
    name?: string; label?: string; field_type?: string; options?: string[] | null;
  }>;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6" onClick={busy ? undefined : onClose}>
      <div className={`w-full max-w-xl h-[75vh] flex flex-col rounded-2xl border overflow-hidden shadow-2xl ${
        dark ? 'border-[#27272a] bg-[#18181b] text-[#fafafa]' : 'border-slate-200 bg-white text-slate-900'
      }`} onClick={(e) => e.stopPropagation()}>
        {/* 头部：标题 + 模型/类型 + 草稿状态 */}
        <div className={`shrink-0 px-5 pt-4 pb-3 border-b space-y-2.5 ${dark ? 'border-[#27272a]' : 'border-slate-200'}`}>
          <div className="flex items-start justify-between">
            <div>
              <h3 className="text-base font-bold flex items-center gap-1.5">
                <Sparkles size={16} className="text-blue-500" />
                {mode === 'edit' ? 'AI 修改工具' : 'AI 生成工具'}
              </h3>
              <p className={`text-[11px] mt-0.5 ${muted}`}>
                {mode === 'edit'
                  ? '描述问题或需求，助手自动测试并保存更新'
                  : '描述需求，助手自动生成 → 测试 → 修正 → 保存，无需手动保存'}
              </p>
            </div>
            <button onClick={onClose} className={`cursor-pointer hover:opacity-70 ${dark ? 'text-[#a1a1aa]' : 'text-slate-400'}`}>✕</button>
          </div>
          <div className="flex items-center gap-2">
            {mode === 'create' && (
              <select value={sourceSel} onChange={(e) => setSourceSel(e.target.value)}
                className={`w-36 shrink-0 ${selectCls}`} title="生成类型：留空由 AI 按需求判断">
                <option value="">类型：AI 判断</option>
                <option value="code">代码（Python）</option>
                <option value="openapi">接口（HTTP）</option>
              </select>
            )}
            {mode === 'create' && sourceSel === 'openapi' && (
              <input
                value={apiUrl}
                onChange={(e) => setApiUrl(e.target.value)}
                placeholder="接口地址（选填，填了 AI 直接用真实地址）"
                className={`flex-1 min-w-0 font-mono ${selectCls}`}
              />
            )}
            <select value={modelId} onChange={(e) => setModelId(e.target.value)}
              className={`flex-1 min-w-0 ${selectCls}`} title="生成模型">
              {activeModels.length === 0 && <option value="">暂无可用模型</option>}
              {activeModels.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
            {busy && (
              <span className="shrink-0 flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-blue-500/15 text-blue-400">
                <Loader2 size={11} className="animate-spin" />AI 执行中
              </span>
            )}
            {latestDraft && (
              <span className={`shrink-0 text-[11px] px-2 py-1 rounded ${
                savedId
                  ? 'bg-emerald-500/15 text-emerald-400'
                  : dark ? 'bg-blue-500/15 text-blue-400' : 'bg-blue-50 text-blue-600'
              }`}>
                {savedId ? '✓ 已保存' : `草稿：${latestDraft.name}`}
              </span>
            )}
          </div>
        </div>

        {/* 消息区 */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {/* edit 模式：当前工具信息卡（置顶常驻——用户始终知道在改哪个工具） */}
          {mode === 'edit' && toolInfo && (() => {
            const SrcIcon = toolInfo.source ? SOURCE_META[toolInfo.source]?.icon : undefined;
            return (
              <div className={`rounded-lg border p-2.5 space-y-1 text-[11px] ${
                dark ? 'border-blue-500/30 bg-blue-500/5' : 'border-blue-200 bg-blue-50/40'
              }`}>
                <div className="flex items-center gap-1.5">
                  {SrcIcon && <SrcIcon size={12} className="text-blue-400 shrink-0" />}
                  <span className="font-semibold truncate">{toolInfo.name}</span>
                  {toolInfo.source && (
                    <span className={`px-1.5 py-0.5 rounded shrink-0 ${dark ? 'bg-[#27272a]' : 'bg-slate-100'}`}>
                      {SOURCE_META[toolInfo.source]?.label ?? toolInfo.source}
                    </span>
                  )}
                  <span className={muted}>正在修改此工具</span>
                </div>
                {toolInfo.description && (
                  <div className={muted}>{toolInfo.description}</div>
                )}
              </div>
            );
          })()}
          {/* 空状态引导（创建模式专属示例——edit 模式有工具卡不需要示例） */}
          {mode === 'create' && messages.length === 0 && !streamText && (
            <div className={`py-10 text-center text-xs leading-relaxed ${muted}`}>
              描述你想要的工具开始对话，例如：<br />
              「给指定邮箱发送带附件的邮件」「把上传的 CSV 汇总成 Excel 报表」<br />
              助手会自动测试并保存；需要凭证时会在对话里向你索取
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.kind === 'user' ? 'justify-end' : 'justify-start'}`}>
              {m.kind === 'user' ? (
                <div className="max-w-[85%] px-3 py-2 rounded-xl text-xs whitespace-pre-wrap break-words bg-blue-600 text-white">
                  {m.content}
                </div>
              ) : m.kind === 'assistant' ? (
                <div className={`max-w-[85%] px-3 py-2 rounded-xl text-xs break-words ${
                  dark ? 'bg-[#27272a] text-[#e4e4e7]' : 'bg-slate-100 text-slate-700'
                }`}>
                  <Markdown content={m.content} />
                </div>
              ) : (
                <div className={`max-w-[85%] w-full rounded-lg border px-2.5 py-2 space-y-1 text-[11px] ${
                  m.status === 'error'
                    ? dark ? 'border-red-500/30 bg-red-500/5' : 'border-red-200 bg-red-50/40'
                    : dark ? 'border-[#27272a] bg-[#121214]/60' : 'border-slate-200 bg-slate-50/70'
                }`}>
                  <div className="flex items-center gap-1.5">
                    {m.status === 'run' && <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />}
                    <span className="font-semibold">{TOOL_LABEL[m.name] ?? m.name}</span>
                    {m.status !== 'run' && (
                      <span className={m.status === 'ok' ? 'text-emerald-500' : 'text-red-400'}>
                        {m.status === 'ok' ? '✓' : '✗'}
                      </span>
                    )}
                  </div>
                  {m.detail && (
                    <pre className={`whitespace-pre-wrap break-all max-h-32 overflow-y-auto font-mono ${muted}`}>{m.detail}</pre>
                  )}
                </div>
              )}
            </div>
          ))}
          {streamText && (
            <div className="flex justify-start">
              <div className={`max-w-[85%] px-3 py-2 rounded-xl text-xs break-words ${
                dark ? 'bg-[#27272a] text-[#e4e4e7]' : 'bg-slate-100 text-slate-700'
              }`}>
                <Markdown content={streamText} />
              </div>
            </div>
          )}
          {/* AI 执行中动效：跳动圆点（等待模型/工具执行间隙——沙箱测试可达数十秒） */}
          {busy && !streamText && (
            <div className="flex justify-start">
              <div className={`px-3.5 py-3 rounded-xl flex items-end gap-1.5 ${dark ? 'bg-[#27272a]' : 'bg-slate-100'}`}>
                {[0, 150, 300].map((delay) => (
                  <span
                    key={delay}
                    className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce"
                    style={{ animationDelay: `${delay}ms` }}
                  />
                ))}
              </div>
            </div>
          )}

          {/* interrupt 卡：fields 表单（凭证等）或选项/文本作答；有草稿时
              提供「跳过测试直接保存」（AI 提问文案常提到可跳过——对应出口） */}
          {interrupt && !busy && (
            <div className={`rounded-lg border p-3 space-y-2 text-xs ${
              dark ? 'border-amber-500/30 bg-amber-500/5' : 'border-amber-200 bg-amber-50/50'
            }`}>
              <div className="font-semibold">{interrupt.question}</div>
              {interrupt.context && <div className={muted}>{interrupt.context}</div>}
              {fieldList.length > 0 ? (
                <div className="space-y-1.5">
                  {fieldList.map((f, idx) => {
                    const key = f.name ?? `field_${idx}`;
                    return (
                      <label key={key} className="block space-y-0.5">
                        <span className={muted}>{f.label ?? key}</span>
                        <input
                          type={/密|密码|password|secret|token|key/i.test(f.label ?? '') ? 'password' : 'text'}
                          value={fieldAnswers[key] ?? ''}
                          onChange={(e) => setFieldAnswers((prev) => ({ ...prev, [key]: e.target.value }))}
                          className={`w-full font-mono ${ctlCls}`}
                        />
                      </label>
                    );
                  })}
                  <div className="flex gap-1.5">
                    <button
                      onClick={() => {
                        const filled = Object.fromEntries(
                          Object.entries(fieldAnswers).filter(([, v]) => v.trim() !== ''),
                        );
                        if (!Object.keys(filled).length) { toast.error('请至少填写一项，或选择跳过'); return; }
                        void answer(filled);
                      }}
                      className="flex-1 px-3 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white cursor-pointer transition flex items-center justify-center gap-1.5">
                      <Play size={12} />提交并继续
                    </button>
                    {latestDraft && (
                      <button onClick={() => void answer('跳过测试，直接保存')}
                        className={`px-3 py-1.5 rounded text-xs border cursor-pointer transition ${
                          dark
                            ? 'border-[#3f3f46] text-[#d4d4d8] hover:border-blue-500/60 hover:text-blue-400'
                            : 'border-slate-300 text-slate-600 hover:border-blue-400 hover:text-blue-600'
                        }`}>
                        跳过测试，直接保存
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {(interrupt.options ?? []).map((opt) => (
                    <button key={opt} onClick={() => void answer(opt)}
                      className={`px-2.5 py-1 rounded border cursor-pointer transition ${
                        dark ? 'border-[#3f3f46] text-[#d4d4d8] hover:border-blue-500/60' : 'border-slate-300 text-slate-600 hover:border-blue-400'
                      }`}>
                      {opt}
                    </button>
                  ))}
                  {latestDraft && (
                    <button onClick={() => void answer('跳过测试，直接保存')}
                      className={`px-2.5 py-1 rounded border cursor-pointer transition ${
                        dark ? 'border-[#3f3f46] text-[#d4d4d8] hover:border-blue-500/60' : 'border-slate-300 text-slate-600 hover:border-blue-400'
                      }`}>
                      跳过测试，直接保存
                    </button>
                  )}
                  <span className={muted}>或直接在下方输入框回复</span>
                </div>
              )}
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* 输入区 */}
        <div className={`shrink-0 px-5 py-3 border-t flex items-end gap-2 ${dark ? 'border-[#27272a]' : 'border-slate-200'}`}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                // interrupt 挂起时输入框回复即作答（无 fields 场景）
                if (interrupt && !fieldList.length) void answer(input.trim() || '（跳过）');
                else void send();
              }
            }}
            rows={2}
            placeholder={messages.length === 0 ? '描述你想要的工具…' : '继续提修改意见，或直接回车发送…'}
            className={`flex-1 min-w-0 resize-none ${ctlCls}`}
          />
            <button onClick={() => {
              if (interrupt && !fieldList.length) void answer(input.trim() || '（跳过）');
              else void send();
            }} disabled={busy || !input.trim()}
              className="shrink-0 px-3 py-2 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white cursor-pointer transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1">
              {busy
                ? <><Loader2 size={12} className="animate-spin" />执行中</>
                : <><Send size={12} />发送</>}
            </button>
        </div>
      </div>
    </div>
  );
}
