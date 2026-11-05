/**
 * SessionSidebar — 会话列表：新对话 + 搜索 + 时间分组（今天 / 7 天内 / 更早）。
 * 会话级「运行中」状态点依赖后端会话状态接口（BACKEND_GAPS G10），当前按时间分组。
 */
import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Search, Trash2 } from 'lucide-react';
import { sessionApi, sessionKeys, type Session } from '../../services/session-api';

function groupOf(updatedAt: string): 'today' | 'week' | 'earlier' {
  const d = new Date(updatedAt).getTime();
  const now = Date.now();
  const dayStart = new Date().setHours(0, 0, 0, 0);
  if (d >= dayStart) return 'today';
  if (d >= now - 7 * 86400_000) return 'week';
  return 'earlier';
}
const GROUP_LABEL = { today: '今天', week: '7 天内', earlier: '更早' } as const;

export function SessionSidebar({
  activeSessionId, onSelect, onNew, width, agentId,
}: {
  activeSessionId: string | null;
  onSelect: (s: Session) => void;
  onNew: () => void;
  /** 宽度 px（可拖拽调，ChatPage 控制） */
  width: number;
  /** 按当前 Agent 过滤会话（切 Agent 不串消息） */
  agentId?: string;
}) {
  const qc = useQueryClient();
  const [kw, setKw] = useState('');
  const { data } = useQuery({
    queryKey: [...sessionKeys.lists(), { agent_id: agentId }],
    queryFn: () => sessionApi.list({ page_size: 50, agent_id: agentId || undefined }),
  });

  const groups = useMemo(() => {
    const items = (data?.items ?? [])
      .filter((s) => !kw || s.title.toLowerCase().includes(kw.toLowerCase()))
      .sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at));
    const g: Record<string, Session[]> = { today: [], week: [], earlier: [] };
    for (const s of items) g[groupOf(s.updated_at)].push(s);
    return g;
  }, [data, kw]);

  const remove = async (e: React.MouseEvent, s: Session) => {
    e.stopPropagation();
    await sessionApi.remove(s._id);
    qc.invalidateQueries({ queryKey: sessionKeys.lists() });
    if (s._id === activeSessionId) onNew();
  };

  return (
    <aside style={{ width }} className="flex flex-none flex-col border-r border-line bg-well">
      <div className="px-2.5 pb-1.5 pt-3">
        <button onClick={onNew} className="af-btn w-full">＋ 新对话</button>
      </div>
      <div className="mx-2.5 mb-2 flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2.5 py-1.5">
        <Search size={12} className="text-ink-faint" />
        <input
          value={kw}
          onChange={(e) => setKw(e.target.value)}
          placeholder="搜索会话"
          className="w-full bg-transparent text-[11px] text-ink outline-none placeholder:text-ink-faint"
        />
      </div>
      <div className="scrollbar-custom min-h-0 flex-1 overflow-y-auto pb-3">
        {(['today', 'week', 'earlier'] as const).map((g) =>
          groups[g].length > 0 ? (
            <div key={g}>
              <div className="px-3.5 pb-1 pt-2 text-[9px] font-bold uppercase tracking-wider text-ink-faint">
                {GROUP_LABEL[g]}
              </div>
              {groups[g].map((s) => (
                <button
                  key={s._id}
                  onClick={() => onSelect(s)}
                  className={`group mx-1.5 flex w-[calc(100%-12px)] items-center rounded-[9px] px-2.5 py-[7px] text-left ${
                    s._id === activeSessionId ? 'bg-brand-soft' : 'hover:bg-panel-hover'
                  }`}
                >
                  <span className="min-w-0 flex-1">
                    <b className={`block truncate text-[11px] ${s._id === activeSessionId ? 'text-brand' : 'text-ink'}`}>
                      {s.title || '未命名会话'}
                    </b>
                    <span className="block text-[9.5px] text-ink-faint">{s.message_count} 条消息</span>
                  </span>
                  <span
                    onClick={(e) => remove(e, s)}
                    className="hidden text-ink-faint hover:text-danger group-hover:block"
                    title="删除会话"
                  >
                    <Trash2 size={12} />
                  </span>
                </button>
              ))}
            </div>
          ) : null,
        )}
      </div>
    </aside>
  );
}
