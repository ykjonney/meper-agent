import { useEffect, useRef, useState } from 'react';
import { Circle, CircleCheck, CircleDot, ClipboardList } from 'lucide-react';
import type { TodoItem } from './message-utils';

/** TodoPanel — 顶栏右侧任务清单：折叠胶囊(n/m 进度) + 点击展开最新快照卡。
 *  数据由 ChatHomepage 从 timeline 派生（extractLatestTodos）；清单清空
 *  （todos=[]，任务闭环）由调用方整个卸载，本组件不处理空列表。
 *  状态视觉：进行中 text-brand / 完成 text-ink-faint 删除线 / 待办 text-ink-soft；
 *  全语义 token，theme-indigo 明暗自适应，无 theme prop。 */
export function TodoPanel({ todos }: { todos: TodoItem[] }) {
  const [open, setOpen] = useState(false);
  const openRef = useRef(open);
  openRef.current = open;
  const autoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 挂载即自动展开一次（让用户注意到清单建立），2.5s 后自动收起；
  // 手动 toggle 取消未触发的定时器（手动操作优先）。
  useEffect(() => {
    setOpen(true);
    autoTimer.current = setTimeout(() => {
      if (openRef.current) setOpen(false);
    }, 2500);
    return () => {
      if (autoTimer.current) clearTimeout(autoTimer.current);
    };
  }, []);

  const toggle = () => {
    if (autoTimer.current) {
      clearTimeout(autoTimer.current);
      autoTimer.current = null;
    }
    setOpen((v) => !v);
  };

  const done = todos.filter((t) => t.status === 'completed').length;
  const doing = todos.some((t) => t.status === 'in_progress');
  const allDone = done === todos.length;
  const accent = allDone ? 'text-sig-ok' : doing ? 'text-brand' : 'text-ink-dim';
  // 全完成收尾：胶囊淡化为弱灰度不抢视觉（hover/展开复原）——清单仍可
  // 回看，新一轮 todo_write 全量替换后自然恢复常态。
  const faded = allDone && !open;

  return (
    <div className="relative shrink-0">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className={`h-8 flex items-center gap-1.5 px-2.5 bg-panel border border-line rounded-full shadow-[var(--shadow-card)] cursor-pointer transition hover:border-line-strong ${faded ? 'opacity-45 hover:opacity-100' : ''}`}
        title="任务清单"
      >
        <ClipboardList className={`w-3.5 h-3.5 ${accent}`} />
        <span className={`text-[11px] font-semibold font-mono tabular-nums ${accent}`}>
          {done}/{todos.length}
        </span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={toggle} />
          <div className="absolute right-0 top-full mt-2 z-50 w-72 bg-panel rounded-[10px] shadow-[var(--shadow-pop)] border border-line p-1.5 animate-fade-in">
            <div className="px-2 pt-1 pb-1.5 flex items-center gap-1.5">
              <span className="af-label">任务清单</span>
              <span className={`ml-auto text-[10.5px] font-mono tabular-nums ${allDone ? 'text-sig-ok' : 'text-ink-faint'}`}>
                {done}/{todos.length}
              </span>
            </div>
            <ul className="flex flex-col gap-0.5">
              {todos.map((t, i) => (
                <li key={i} className="flex items-center gap-2 px-2 py-1 rounded-lg">
                  {t.status === 'completed' ? (
                    <CircleCheck className="w-3.5 h-3.5 shrink-0 text-ink-faint" />
                  ) : t.status === 'in_progress' ? (
                    <CircleDot className="w-3.5 h-3.5 shrink-0 text-brand" />
                  ) : (
                    <Circle className="w-3.5 h-3.5 shrink-0 text-ink-soft" />
                  )}
                  <span
                    className={`min-w-0 flex-1 text-[12px] truncate ${
                      t.status === 'completed'
                        ? 'text-ink-faint line-through'
                        : t.status === 'in_progress'
                          ? 'text-ink font-medium'
                          : 'text-ink-soft'
                    }`}
                  >
                    {t.content}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
