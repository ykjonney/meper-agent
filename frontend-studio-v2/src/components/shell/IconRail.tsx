import { useCallback, useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { useAuthStore } from '../../stores/auth-store';

/**
 * 64px 图标窄栏 — 照抄预览稿样式（emoji 图标 + 渐变 ✦ logo）。
 * 权限门控沿用 v1 语义：无权限的一级项整个隐藏。
 */
interface RailItem {
  to: string;
  label: string;
  emoji: string;
  /** 任一满足即可见；undefined = 永远可见 */
  permission?: string[];
}

const RAIL_ITEMS: RailItem[] = [
  { to: '/home', label: '首页', emoji: '⌂' },
  { to: '/chat', label: '对话', emoji: '💬' },
  { to: '/tasks', label: '任务', emoji: '☑' },
  { to: '/agents', label: '智能体', emoji: '🤖', permission: ['agent:read'] },
  { to: '/knowledge', label: '知识库', emoji: '📚', permission: ['knowledge:read'] },
  { to: '/tools', label: '工具', emoji: '🧰', permission: ['tool:read'] },
];

const THEME_KEY = 'agentflow_v2_theme';

function useTheme() {
  const [dark, setDark] = useState(
    () => document.documentElement.classList.contains('theme-dark'),
  );
  useEffect(() => {
    document.documentElement.classList.toggle('theme-dark', dark);
    localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light');
  }, [dark]);
  const toggle = useCallback(() => setDark((v) => !v), []);
  return { dark, toggle };
}

export function IconRail() {
  const role = useAuthStore((s) => s.user?.role);
  const isAdmin = role === 'admin';
  const { dark, toggle } = useTheme();

  return (
    <nav className="flex w-[76px] flex-none flex-col items-center gap-1.5 border-r border-line bg-panel py-3.5">
      {/* Logo → 首页（预览稿：渐变 ✦） */}
      <NavLink
        to="/home"
        className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl text-[17px] text-white shadow-card"
        style={{ background: 'linear-gradient(135deg, var(--color-brand-grad-from), var(--color-brand-grad-to))' }}
        title="Agent Flow"
      >
        ✦
      </NavLink>

      {RAIL_ITEMS.map(({ to, label, emoji, permission }) => (
        <RailLink key={to} to={to} label={label} emoji={emoji} permission={permission} />
      ))}

      <div className="flex-1" />

      {isAdmin && <RailLink to="/admin" label="管理" emoji="⚙" />}

      {/* 明暗主题切换 */}
      <button
        onClick={toggle}
        title={dark ? '切换到亮色' : '切换到暗色'}
        className="flex w-14 flex-col items-center gap-1 rounded-xl py-2 text-ink-dim transition-colors hover:bg-panel-hover hover:text-ink-soft"
      >
        <span className="text-[17px] leading-none">{dark ? '☀️' : '🌙'}</span>
        <span className="text-[11px]">{dark ? '亮色' : '暗色'}</span>
      </button>

      <RailLink to="/profile" label="我" emoji="👤" />
    </nav>
  );
}

function RailLink({
  to, label, emoji, permission,
}: { to: string; label: string; emoji: string; permission?: string[] }) {
  // 权限数组 = 任一满足即可见（与 v1 App.tsx NAV_ITEMS 语义一致）
  const permissions = useAuthStore((s) => s.user?.permissions);
  if (permission && !permissions?.some((p) => permission.includes(p))) return null;
  return (
    <NavLink
      to={to}
      title={label}
      className={({ isActive }) =>
        `flex w-14 flex-col items-center gap-1 rounded-xl py-2 text-[11.5px] transition-colors ${
          isActive
            ? 'bg-brand-soft font-bold text-brand'
            : 'text-ink-dim hover:bg-panel-hover hover:text-ink-soft'
        }`
      }
    >
      <span className="text-[19px] leading-none">{emoji}</span>
      {label}
    </NavLink>
  );
}
