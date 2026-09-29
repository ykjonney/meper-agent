/**
 * SegmentedTabs — 页面内主导航的分段式 Tab 控件（统一三处页内 Tab 风格：
 * 系统设置 / 工具库 / 技能）。带边框容器 + 圆角分段，激活段蓝底白字，
 * 未激活段 muted 悬停提亮；支持可选图标，dark/light 双主题。
 */
import type { LucideIcon } from 'lucide-react';

export interface SegmentedTabItem<T extends string> {
  id: T;
  label: string;
  icon?: LucideIcon;
}

interface Props<T extends string> {
  tabs: SegmentedTabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  theme: 'dark' | 'light';
}

export function SegmentedTabs<T extends string>({ tabs, value, onChange, theme }: Props<T>) {
  return (
    <div
      role="tablist"
      className={`inline-flex items-center gap-1 rounded-lg border p-0.5 ${
        theme === 'dark' ? 'border-[#27272a] bg-[#18181b]' : 'border-slate-200 bg-white'
      }`}
    >
      {tabs.map((t) => {
        const active = t.id === value;
        const Icon = t.icon;
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium cursor-pointer transition ${
              active
                ? 'bg-blue-600 text-white'
                : theme === 'dark'
                  ? 'text-[#a1a1aa] hover:text-[#fafafa]'
                  : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {Icon && <Icon size={13} className="shrink-0" />}
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
