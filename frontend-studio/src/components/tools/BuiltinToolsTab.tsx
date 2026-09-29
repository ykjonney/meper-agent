/** BuiltinToolsTab — 工具库页「系统内置」Tab：内置工具只读卡片墙。
 *
 * 数据同旧 BuiltinToolsPage（toolsApi.listBuiltins），queryKey 沿用
 * ['builtin-tools'] 与 AgentEditorPage 共享缓存。内置工具由运行时代码
 * 生成（无 id/状态），卡片只读：图标 + 名称 + 描述 + 参数名 tag。
 * 搜索为客户端过滤（组织工具 Tab 是服务端 q 搜索）。
 */
import { useMemo } from 'react';
import {
  Terminal, BookOpen, FilePen, FileSearch, Wrench, Code, type LucideIcon,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { toolsApi, type BuiltinTool } from '../../services/tools-api';

/** Map a builtin tool name → lucide icon + accent color. */
function iconFor(name: string): { Icon: LucideIcon; color: string } {
  const n = name.toLowerCase();
  if (n.includes('bash') || n.includes('shell') || n.includes('exec')) {
    return { Icon: Terminal, color: 'text-emerald-400 bg-emerald-500/10' };
  }
  if (n.includes('run_code') || n.includes('code')) {
    return { Icon: Code, color: 'text-amber-400 bg-amber-500/10' };
  }
  if (n.includes('read') || n.includes('fetch') || n.includes('get')) {
    return { Icon: BookOpen, color: 'text-sky-400 bg-sky-500/10' };
  }
  if (n.includes('write') || n.includes('edit') || n.includes('create') || n.includes('update')) {
    return { Icon: FilePen, color: 'text-indigo-400 bg-indigo-500/10' };
  }
  if (n.includes('parse') || n.includes('extract')) {
    return { Icon: FileSearch, color: 'text-violet-400 bg-violet-500/10' };
  }
  return { Icon: Wrench, color: 'text-zinc-400 bg-zinc-500/10' };
}

/** Extract parameter names from a JSON-Schema-style parameters object. */
function paramNames(params: Record<string, unknown> | undefined): string[] {
  const props = params?.properties;
  if (props && typeof props === 'object') {
    return Object.keys(props as Record<string, unknown>);
  }
  return [];
}

interface Props {
  /** 与组织工具 Tab 共用顶部搜索框 */
  q: string;
  theme: 'dark' | 'light';
}

export function BuiltinToolsTab({ q, theme }: Props) {
  const { data: tools, isLoading } = useQuery({
    queryKey: ['builtin-tools'],
    queryFn: () => toolsApi.listBuiltins(),
  });

  const filtered = useMemo(() => {
    const list = tools ?? [];
    const kw = q.trim().toLowerCase();
    if (!kw) return list;
    return list.filter((t) =>
      [t.name, t.description].some((v) => v.toLowerCase().includes(kw)),
    );
  }, [tools, q]);

  const textMuted = theme === 'dark' ? 'text-[#a1a1aa]' : 'text-slate-500';

  if (isLoading) {
    return <div className="py-12 text-center text-sm opacity-60">加载中…</div>;
  }
  if (filtered.length === 0) {
    return (
      <div className={`py-12 text-center text-sm ${textMuted}`}>
        暂无内置工具{q ? '——换个关键词试试' : ''}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
      {filtered.map((t) => (
        <BuiltinCard key={t.name} tool={t} theme={theme} />
      ))}
    </div>
  );
}

function BuiltinCard({ tool, theme }: { tool: BuiltinTool; theme: 'dark' | 'light' }) {
  const { Icon, color } = iconFor(tool.name);
  const params = paramNames(tool.parameters);
  const card = theme === 'dark'
    ? 'bg-[#18181b] border-[#27272a] hover:border-[#71717a]'
    : 'bg-white border-slate-200 hover:border-slate-300';
  const textMuted = theme === 'dark' ? 'text-[#a1a1aa]' : 'text-slate-500';
  const chip = theme === 'dark'
    ? 'bg-[#121214] border-[#27272a] text-[#a1a1aa]'
    : 'bg-slate-100 border-slate-200 text-slate-500';

  return (
    <div className={`rounded-xl border p-5 flex flex-col gap-3 transition ${card}`}>
      <div className="flex items-start gap-3 min-w-0">
        <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${color}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-bold font-mono truncate" title={tool.name}>{tool.name}</h3>
          <p className={`text-xs ${textMuted} mt-1 line-clamp-2 leading-relaxed`}>
            {tool.description || '无描述'}
          </p>
        </div>
      </div>
      <div className={`flex flex-wrap gap-1.5 pt-1 border-t ${
        theme === 'dark' ? 'border-[#27272a]' : 'border-slate-200'
      }`}>
        {params.length === 0 ? (
          <span className="text-[10px] text-[#52525b]">无参数</span>
        ) : (
          params.map((p) => (
            <span key={p} className={`px-1.5 py-0.5 rounded border text-[10px] font-mono ${chip}`}>
              {p}
            </span>
          ))
        )}
      </div>
    </div>
  );
}
