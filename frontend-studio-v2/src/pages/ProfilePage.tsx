/**
 * ProfilePage — 个人设置：当前身份 + 偏好（主题切换说明）。
 * 密码修改/头像等个人域设置 P4.5 接入。
 */
import { useAuthStore } from '../stores/auth-store';
import { FlowMark } from '../components/shell/FlowMark';

export function ProfilePage() {
  const user = useAuthStore((s) => s.user);

  return (
    <div className="h-full overflow-y-auto scrollbar-custom bg-canvas">
      <div className="mx-auto max-w-lg px-6 py-8">
        <div className="af-label mb-1">ACCOUNT / 个人设置</div>
        <h1 className="mb-6 text-xl font-extrabold tracking-tight">我的账户</h1>

        <div className="af-card mb-4 flex items-center gap-4 px-5 py-5">
          <span
            className="flex h-14 w-14 flex-none items-center justify-center rounded-xl text-[var(--color-on-brand)]"
            style={{ background: 'var(--color-brand)' }}
          >
            <FlowMark size={26} />
          </span>
          <div className="min-w-0">
            <div className="text-[15px] font-bold text-ink">{user?.username ?? '—'}</div>
            <div className="mt-0.5 flex items-center gap-2">
              <span className="af-pill af-pill-brand font-mono">{user?.role ?? 'member'}</span>
              {user?.isSuperAdmin && <span className="af-pill af-pill-warning font-mono">SUPER ADMIN</span>}
            </div>
          </div>
        </div>

        <div className="af-card px-5 py-4">
          <div className="af-label mb-3">PERMISSIONS / 权限域（{user?.permissions.length ?? 0}）</div>
          <div className="flex flex-wrap gap-1.5">
            {(user?.permissions ?? []).map((p) => (
              <span key={p} className="af-pill af-pill-neutral font-mono">{p}</span>
            ))}
            {(user?.permissions ?? []).length === 0 && <span className="text-[11.5px] text-ink-faint">—</span>}
          </div>
        </div>

        <div className="mt-4 rounded-lg border border-dashed border-line px-4 py-3 text-[11px] text-ink-faint">
          主题切换在左侧图标栏底部（☀/🌙）；密码与头像设置 P4.5 接入。
        </div>
      </div>
    </div>
  );
}
