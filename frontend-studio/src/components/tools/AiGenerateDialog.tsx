/** AI 生成对话框（聊天式）——从 ToolMarketPage 拆出，行为不变。
 * 描述 → 生成 → 提修改意见 → 修订，满意后填入创建表单；生成不落库、
 * 不绕过治理。seed：修改已有工具场景——把已保存定义作为对话首条消息。 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Sparkles } from 'lucide-react'
import { getErrorMessage } from '../../lib/api-client'
import { toast } from '../ui/toast'
import { Markdown } from '../Markdown'
import { useActiveModels } from '../../hooks/use-active-models'
import { userToolsApi, type GeneratedToolDraft } from '../../services/user-tools-api'

/** AI 生成对话框（聊天式）：描述 → 生成 → 提修改意见 → 修订，满意后填入创建表单。
 * 生成不落库、不绕过治理——用户检查/修改后正常走 create → submit → review。
 * seed：修改已有工具场景——把已保存定义作为对话首条 assistant 消息。 */
export function AiGenerateDialog({ dark, onClose, onApply, seed, applyLabel = '填入创建表单' }: {
  dark: boolean; onClose: () => void; onApply: (d: GeneratedToolDraft) => void;
  seed?: { content: string; draft: GeneratedToolDraft } | null;
  applyLabel?: string;
}) {
  type ChatMsg = { role: 'user' | 'assistant'; content: string; draft?: GeneratedToolDraft };
  const [messages, setMessages] = useState<ChatMsg[]>(
    seed ? [{ role: 'assistant', content: seed.content, draft: seed.draft }] : [],
  );
  const [input, setInput] = useState('');
  const [sourceSel, setSourceSel] = useState('');
  const [apiUrl, setApiUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const { activeModels, modelId, setModelId } = useActiveModels();
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, busy]);

  const latestDraft = [...messages].reverse().find((m) => m.role === 'assistant' && m.draft)?.draft;

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    const fullText = apiUrl.trim() && sourceSel === 'openapi'
      ? `${text}\n（工具要调用的接口地址：${apiUrl.trim()}）`
      : text;
    const next: ChatMsg[] = [...messages, { role: 'user', content: fullText }];
    setMessages(next);
    setInput('');
    setBusy(true);
    try {
      // assistant 历史重构为「说明 + 围栏草稿」——AI 能看到上一版做修订
      const history = next.map((m) => ({
        role: m.role,
        content: m.role === 'assistant' && m.draft
          ? `${m.content}\n\`\`\`json\n${JSON.stringify(m.draft, null, 2)}\n\`\`\``
          : m.content,
      }));
      const { reply, draft } = await userToolsApi.generate({
        messages: history, source: sourceSel, model_id: modelId,
      });
      setMessages((prev) => [...prev, {
        role: 'assistant', content: reply, draft: draft ?? undefined,
      }]);
    } catch (e) {
      toast.error(getErrorMessage(e, '生成失败，请重试'));
    } finally {
      setBusy(false);
    }
  };

  const muted = dark ? 'text-[#71717a]' : 'text-slate-500';
  // 对话框内控件专用样式——不带 w-full（flex 行内 width:100% 会与兄弟
  // 元素叠加导致横向溢出弹窗边框；宽度交给 flex 布局控制）
  const ctlCls = `px-2 py-1.5 rounded text-xs border outline-none ${
    dark
      ? 'bg-[#121214] border-[#27272a] text-white placeholder:text-[#52525b] focus:border-blue-600'
      : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-blue-500'
  }`;
  const selectCls = `${ctlCls} cursor-pointer`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6" onClick={busy ? undefined : onClose}>
      <div className={`w-full max-w-xl h-[75vh] flex flex-col rounded-2xl border overflow-hidden shadow-2xl ${
        dark ? 'border-[#27272a] bg-[#18181b] text-[#fafafa]' : 'border-slate-200 bg-white text-slate-900'
      }`} onClick={(e) => e.stopPropagation()}>
        {/* 头部：标题 + 模型/类型 + 填表入口 */}
        <div className={`shrink-0 px-5 pt-4 pb-3 border-b space-y-2.5 ${dark ? 'border-[#27272a]' : 'border-slate-200'}`}>
          <div className="flex items-start justify-between">
            <div>
              <h3 className="text-base font-bold flex items-center gap-1.5">
                <Sparkles size={16} className="text-blue-500" />AI 生成工具
              </h3>
              <p className={`text-[11px] mt-0.5 ${muted}`}>
                描述需求生成草稿，继续对话打磨——满意后填入创建表单（治理流程不变）
              </p>
            </div>
            <button onClick={onClose} className={`cursor-pointer hover:opacity-70 ${dark ? 'text-[#a1a1aa]' : 'text-slate-400'}`}>✕</button>
          </div>
          <div className="flex items-center gap-2">
            <select value={sourceSel} onChange={(e) => setSourceSel(e.target.value)}
              className={`w-36 shrink-0 ${selectCls}`} title="生成类型：留空由 AI 按需求判断">
              <option value="">类型：AI 判断</option>
              <option value="code">代码（Python）</option>
              <option value="openapi">接口（HTTP）</option>
            </select>
            {sourceSel === 'openapi' && (
              <input
                value={apiUrl}
                onChange={(e) => setApiUrl(e.target.value)}
                placeholder="接口地址，如 https://api.example.com/v1/weather（选填，填了 AI 直接用真实地址）"
                className={`flex-1 min-w-0 font-mono ${selectCls}`}
              />
            )}
            <select value={modelId} onChange={(e) => setModelId(e.target.value)}
              className={`flex-1 min-w-0 ${selectCls}`} title="生成模型">
              {activeModels.length === 0 && <option value="">暂无可用模型</option>}
              {activeModels.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
            {latestDraft && (
              <button onClick={() => onApply(latestDraft)}
                className="shrink-0 px-3 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white cursor-pointer transition">
                {applyLabel}
              </button>
            )}
          </div>
        </div>

        {/* 消息区 */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {messages.length === 0 && (
            <div className={`py-10 text-center text-xs leading-relaxed ${muted}`}>
              描述你想要的工具开始对话，例如：<br />
              「给指定邮箱发送带附件的邮件」「把上传的 CSV 汇总成 Excel 报表」<br />
              生成后可以继续提要求：「加个抄送参数」「名字改成 notice-sender」
            </div>
          )}
          {messages.length === 0 && seed && (
            <div className={`py-6 text-center text-xs leading-relaxed ${muted}`}>
              已载入当前工具定义（见上方草稿卡）——直接告诉我想怎么改
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] space-y-2 ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
                {m.role === 'user' ? (
                  <div className="px-3 py-2 rounded-xl text-xs whitespace-pre-wrap break-words bg-blue-600 text-white">
                    {m.content}
                  </div>
                ) : (
                  <div className={`px-3 py-2 rounded-xl text-xs break-words ${
                    dark ? 'bg-[#27272a] text-[#e4e4e7]' : 'bg-slate-100 text-slate-700'
                  }`}>
                    <Markdown content={m.content} />
                  </div>
                )}
                {m.draft && (
                  <div className={`rounded-lg border p-2.5 space-y-1 text-[11px] ${
                    dark ? 'border-blue-500/30 bg-blue-500/5' : 'border-blue-200 bg-blue-50/40'
                  }`}>
                    <div className="flex gap-2">
                      <span className={`w-8 shrink-0 ${muted}`}>名称</span>
                      <span className="font-semibold truncate">{m.draft.name}</span>
                    </div>
                    <div className="flex gap-2">
                      <span className={`w-8 shrink-0 ${muted}`}>类型</span>
                      <span>{m.draft.source === 'openapi' ? '接口（HTTP 封装）' : '代码（Python 沙箱执行）'}</span>
                    </div>
                    <div className="flex gap-2">
                      <span className={`w-8 shrink-0 ${muted}`}>说明</span>
                      <span className="flex-1">{m.draft.description}</span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
          {busy && (
            <div className="flex justify-start">
              <div className={`px-3 py-2 rounded-xl text-xs ${dark ? 'bg-[#27272a]' : 'bg-slate-100'}`}>
                生成中…
              </div>
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
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(); }
            }}
            rows={2}
            placeholder={messages.length === 0 ? '描述你想要的工具…' : '继续提修改意见，或直接回车发送…'}
            className={`flex-1 min-w-0 resize-none ${ctlCls}`}
          />
          <button onClick={() => void send()} disabled={busy || !input.trim()}
            className="shrink-0 px-3 py-2 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white cursor-pointer transition disabled:opacity-50 disabled:cursor-not-allowed">
            发送
          </button>
        </div>
      </div>
    </div>
  );
}

