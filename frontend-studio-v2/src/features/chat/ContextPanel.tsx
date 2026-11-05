/**
 * ContextPanel — 右侧上下文面板：运行状态 / 会话文件 / 待办审批。
 * 开关在顶部 header（主人要求）；宽度可拖拽调（ChatPage 控制）。
 * 运行状态细节（PLAN.md 步骤级进度）依赖后端（BACKEND_GAPS G5/G3），当前显示流式态。
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileText } from 'lucide-react';
import { sessionApi, sessionKeys, type SessionFileEntry } from '../../services/session-api';
import type { ChatMessage } from './useChatStream';

export function ContextPanel({
  sessionId, messages, streaming, width,
}: {
  sessionId: string | null;
  messages: ChatMessage[];
  streaming: boolean;
  /** 面板宽度 px（header 开关 + 拖拽控制） */
  width: number;
}) {
  const { data: files } = useQuery({
    queryKey: sessionKeys.files(sessionId ?? 'none'),
    queryFn: () => sessionApi.listFiles(sessionId!),
    enabled: !!sessionId,
  });

  // 待办审批 = 最后一条 isInterrupted 消息（澄清 / 计划）
  const pending = useMemo(() => {
    const last = [...messages].reverse().find((m) => m.isInterrupted);
    if (!last) return null;
    const planEntry = (last.timeline ?? []).find((e) => e.toolName === 'propose_plan');
    const askEntry = (last.timeline ?? []).find((e) => e.toolName === 'ask_clarification');
    if (planEntry) return { kind: 'plan' as const, text: '执行计划等待批准' };
    if (askEntry) return { kind: 'ask' as const, text: 'Agent 向你提问' };
    return { kind: 'ask' as const, text: '等待你的输入' };
  }, [messages]);

  return (
    <aside style={{ width }} className="flex flex-none flex-col gap-2.5 overflow-y-auto border-l border-line bg-well p-3">

      <div>
        <h5 className="mb-1.5 text-[9px] font-bold uppercase tracking-wider text-ink-faint">运行状态</h5>
        <div className="af-card px-2.5 py-2 text-[10px] leading-relaxed text-ink-soft">
          {streaming ? (
            <>执行中<span className="af-pill af-pill-brand float-right">运行中</span></>
          ) : pending ? (
            <>待人工<span className="af-pill af-pill-warning float-right">待处理</span></>
          ) : (
            <>空闲<span className="af-pill af-pill-success float-right">就绪</span></>
          )}
        </div>
      </div>

      <div>
        <h5 className="mb-1.5 text-[9px] font-bold uppercase tracking-wider text-ink-faint">会话文件</h5>
        {!sessionId || !files?.length ? (
          <div className="rounded-[10px] border border-dashed border-line px-2.5 py-2 text-[10px] text-ink-faint">
            暂无文件
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {files.slice(0, 6).map((f) => <FileRow key={f.path} f={f} />)}
          </div>
        )}
      </div>

      {pending && (
        <div>
          <h5 className="mb-1.5 text-[9px] font-bold uppercase tracking-wider text-ink-faint">待办审批</h5>
          <div className="af-card border-line-strong px-2.5 py-2 text-[10px] text-ink-soft">
            <b className="block text-[10.5px] text-ink">
              {pending.kind === 'plan' ? '📋 执行计划' : '❓ 澄清提问'}
            </b>
            {pending.text}
            <span className="af-pill af-pill-warning float-right">待处理</span>
          </div>
        </div>
      )}
    </aside>
  );
}

function FileRow({ f }: { f: SessionFileEntry }) {
  return (
    <div className="af-card flex items-center gap-1.5 px-2.5 py-2 text-[10px] text-ink-soft">
      <FileText size={11} className="flex-none text-info" />
      <span className="truncate" title={f.path}>{f.path.split('/').pop()}</span>
      <span className="af-pill af-pill-success ml-auto flex-none">可下载</span>
    </div>
  );
}
