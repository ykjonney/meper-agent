/** 工具 AI 测试对话框——从 ToolMarketPage 拆出，行为不变。
 * 先询问用户（确认页 + 必填凭证由用户填写，AI 不编造），确认后 AI 生成
 * 用例并自动逐个试跑。以打开时的表单定义为快照运行，不落库。 */
import { useState } from 'react'
import { Wrench } from 'lucide-react'
import { getErrorMessage } from '../../lib/api-client'
import { toast } from '../ui/toast'
import { useActiveModels } from '../../hooks/use-active-models'
import { userToolsApi, type ToolDefinitionPayload, type TestRunResponse } from '../../services/user-tools-api'

export function TestToolDialog({ dark, definition, credFields, onClose }: {
  dark: boolean;
  definition: ToolDefinitionPayload;
  /** 必须由用户填写的凭证参数（开始前必填，AI 不代填） */
  credFields: { key: string; sensitive: boolean }[];
  onClose: () => void;
}) {
  type Case = { name: string; description: string; params: Record<string, unknown>; out?: TestRunResponse };
  const [phase, setPhase] = useState<'confirm' | 'running'>('confirm');
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [cases, setCases] = useState<Case[]>([]);
  const [stage, setStage] = useState<'gen' | 'run' | 'done'>('gen');

  const { activeModels, modelId, setModelId } = useActiveModels();

  const allCredsFilled = credFields.every((f) => (creds[f.key] ?? '').trim() !== '');

  const start = async () => {
    setPhase('running');
    setStage('gen');
    setCases([]);
    try {
      const { cases: generated } = await userToolsApi.testCases({ definition, model_id: modelId });
      const list: Case[] = generated.map((c) => ({
        name: c.name, description: c.description, params: c.params,
      }));
      setCases(list);
      setStage('run');
      for (let i = 0; i < list.length; i++) {
        try {
          const out = await userToolsApi.testRun({ definition, params: list[i].params, user_args: creds });
          setCases((prev) => prev.map((c, idx) => (idx === i ? { ...c, out } : c)));
        } catch (e) {
          const out = { ok: false, error: getErrorMessage(e, '试跑失败') };
          setCases((prev) => prev.map((c, idx) => (idx === i ? { ...c, out } : c)));
        }
      }
      setStage('done');
    } catch (e) {
      toast.error(getErrorMessage(e, '用例生成失败'));
      setPhase('confirm');
      setStage('gen');
    }
  };

  const muted = dark ? 'text-[#71717a]' : 'text-slate-500';
  const ctlCls = `px-2 py-1.5 rounded text-xs border outline-none ${
    dark
      ? 'bg-[#121214] border-[#27272a] text-white placeholder:text-[#52525b] focus:border-blue-600'
      : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-blue-500'
  }`;

  const renderResult = (out: TestRunResponse | undefined, running: boolean) => {
    if (out) {
      return (
        <div className={`mt-1.5 rounded-lg border p-2 text-[11px] font-mono whitespace-pre-wrap break-words ${
          out.ok
            ? dark ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700'
            : dark ? 'border-red-500/30 bg-red-500/5 text-red-300' : 'border-red-200 bg-red-50 text-red-600'
        }`}>
          {out.ok
            ? (typeof out.result === 'string' ? out.result : JSON.stringify(out.result, null, 2))
            : out.error}
        </div>
      );
    }
    if (running) {
      return <div className={`mt-1.5 text-[11px] ${muted}`}>运行中…</div>;
    }
    return null;
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-6" onClick={phase === 'running' && stage === 'done' ? onClose : undefined}>
      <div className={`w-full max-w-xl max-h-[80vh] flex flex-col rounded-2xl border overflow-hidden shadow-2xl ${
        dark ? 'border-[#27272a] bg-[#18181b] text-[#fafafa]' : 'border-slate-200 bg-white text-slate-900'
      }`} onClick={(e) => e.stopPropagation()}>
        <div className={`flex items-start justify-between shrink-0 px-5 pt-4 pb-3 border-b ${dark ? 'border-[#27272a]' : 'border-slate-200'}`}>
          <div>
            <h3 className="text-base font-bold flex items-center gap-1.5">
              <Wrench size={15} className="text-blue-500" />AI 测试工具
            </h3>
            <p className={`text-[11px] mt-0.5 ${muted}`}>
              以打开时的表单定义为快照：AI 生成用例并自动试跑，不落库、不影响治理状态
            </p>
          </div>
          <button onClick={onClose} className={`cursor-pointer hover:opacity-70 ${dark ? 'text-[#a1a1aa]' : 'text-slate-400'}`}>✕</button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {phase === 'confirm' ? (
            <>
              {/* 询问：是否执行 AI 测试 */}
              <div className={`rounded-lg border p-3 text-xs leading-relaxed ${
                dark ? 'border-blue-500/30 bg-blue-500/5' : 'border-blue-200 bg-blue-50/50'
              }`}>
                即将进行 AI 自动测试：生成 2-3 个用例（含正常路径与边界）并逐个试跑，
                会调用所选模型并执行工具。确认开始？
              </div>

              {/* 必须用户填写的凭证参数（AI 不代填，开始前必填） */}
              {credFields.length > 0 && (
                <div className="space-y-2">
                  <p className={`text-xs ${muted}`}>
                    工具声明的凭证参数需要你填写（仅本次测试用，不保存）：
                  </p>
                  {credFields.map((f) => (
                    <div key={f.key} className="flex items-center gap-2">
                      <label className="w-28 shrink-0 text-xs text-slate-400 truncate" title={f.key}>
                        {f.key}
                        <span className="text-red-500"> *</span>
                      </label>
                      <input
                        type={f.sensitive ? 'password' : 'text'}
                        value={creds[f.key] ?? ''}
                        onChange={(e) => setCreds((prev) => ({ ...prev, [f.key]: e.target.value }))}
                        placeholder={`测试用 ${f.key}`}
                        className={`flex-1 ${ctlCls}`}
                      />
                    </div>
                  ))}
                </div>
              )}

              <div className="flex items-center gap-2">
                <select value={modelId} onChange={(e) => setModelId(e.target.value)}
                  className={`flex-1 min-w-0 ${ctlCls} cursor-pointer`}>
                  {activeModels.length === 0 && <option value="">暂无可用模型</option>}
                  {activeModels.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                </select>
                <button onClick={() => void start()} disabled={!activeModels.length || !allCredsFilled}
                  className="shrink-0 px-3 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white cursor-pointer transition disabled:opacity-50 disabled:cursor-not-allowed"
                  title={credFields.length && !allCredsFilled ? '请先填写凭证参数' : undefined}>
                  开始 AI 测试
                </button>
              </div>
            </>
          ) : (
            <>
              {stage === 'gen' && (
                <div className={`py-8 text-center text-xs ${muted}`}>AI 正在生成测试用例…</div>
              )}
              {cases.map((c, i) => (
                <div key={i} className={`rounded-lg border p-3 space-y-1.5 ${dark ? 'border-[#27272a]' : 'border-slate-200'}`}>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold truncate">{c.name}</span>
                    {c.description && <span className={`text-[10px] ${muted} truncate`}>{c.description}</span>}
                  </div>
                  <div className={`text-[11px] font-mono break-words ${muted}`}>
                    {JSON.stringify(c.params)}
                  </div>
                  {renderResult(c.out, stage === 'run' && !c.out)}
                </div>
              ))}
              {stage === 'done' && (
                <div className="flex items-center justify-between pt-1">
                  <span className={`text-xs ${muted}`}>
                    完成：{cases.filter((c) => c.out?.ok).length}/{cases.length} 通过
                    （边界用例失败不一定是问题，看验证点说明）
                  </span>
                  <button onClick={() => setPhase('confirm')}
                    className={`px-3 py-1.5 rounded text-xs font-medium cursor-pointer ${
                      dark ? 'border border-[#27272a] hover:bg-[#27272a]' : 'border border-slate-200 hover:bg-slate-50'
                    }`}>
                    重新测试
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}


