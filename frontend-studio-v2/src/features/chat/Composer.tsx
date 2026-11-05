/**
 * Composer — 输入框（v2 打磨版）：
 * · focus 聚焦反馈：品牌色描边 + 柔光晕
 * · 模式开关：lucide 图标 + 文字（激活=淡紫底紫字），弃用 emoji（渲染不一致）
 * · 发送 32px 渐变方块 / 停止深色按钮；工具图标 hover 淡紫底
 * · 计划模式激活时顶部状态条；执行中锁定开关、发送→停止
 */
import { useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react';
import {
  Plus, Paperclip, AtSign, Mic, SendHorizontal, Square, X,
  ClipboardList, Brain, Globe,
} from 'lucide-react';
import { isImeComposing } from '../../lib/keyboard';

export interface ComposerState {
  planMode: boolean;
  thinking: boolean;
  webSearch: boolean;
}

export function Composer({
  agentName, agentModel, streaming, disabled,
  onSend, onStop, state, onStateChange,
  draft, onDraftChange,
}: {
  agentName?: string;
  agentModel: string;
  streaming: boolean;
  disabled?: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  state: ComposerState;
  onStateChange: (next: ComposerState) => void;
  /** 草稿（按会话保留，上层持有） */
  draft: string;
  onDraftChange: (v: string) => void;
}) {
  const text = draft;
  const [focused, setFocused] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const setText = (v: string) => onDraftChange(v);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t || streaming || disabled) return;
    onSend(t);
    setText('');
    if (taRef.current) taRef.current.style.height = 'auto';
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !isImeComposing(e)) {
      e.preventDefault();
      submit();
    }
  };

  const autoGrow = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  };

  return (
    <div
      className={`mb-4 overflow-hidden rounded-2xl border bg-panel transition-all duration-150 ${
        focused
          ? 'border-brand shadow-[0_0_0_3px_var(--color-brand-soft),var(--shadow-composer)]'
          : 'border-line-strong shadow-composer hover:border-ink-faint/60'
      }`}
    >
      {/* 计划模式激活状态条 */}
      {state.planMode && (
        <div className="mx-3 mt-3 flex w-fit items-center gap-1.5 rounded-lg bg-brand-soft px-2.5 py-1 text-[11px] font-semibold text-brand">
          <ClipboardList size={11} />
          计划模式已开启 — 回复将先规划后执行
          <button
            onClick={() => onStateChange({ ...state, planMode: false })}
            className="ml-0.5 text-ink-faint transition-colors hover:text-ink"
            title="关闭计划模式"
          >
            <X size={11} />
          </button>
        </div>
      )}

      <textarea
        ref={taRef}
        value={text}
        rows={1}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onChange={(e) => { setText(e.target.value); autoGrow(e.target); }}
        onKeyDown={onKeyDown}
        placeholder={streaming ? 'Agent 工作中 — 可随时插入补充指令…' : `向 ${agentName ?? 'Agent'} 下达任务或提问…`}
        disabled={disabled}
        className="w-full resize-none bg-transparent px-4 pb-2 pt-3.5 text-[13.5px] leading-relaxed text-ink outline-none placeholder:text-ink-faint disabled:opacity-60"
      />

      <div className="flex items-center gap-1 px-2 pb-2 pt-0.5">
        {/* 附件组：P3.5 接线，先占位 */}
        <IconBtn title="附件（即将上线）" disabled><Plus size={16} /></IconBtn>
        <IconBtn title="上传文件（即将上线）" disabled><Paperclip size={15} /></IconBtn>
        <IconBtn title="@ 技能（即将上线）" disabled><AtSign size={15} /></IconBtn>

        <span className="mx-1 h-4 w-px bg-line" />

        {/* 模式开关 */}
        <ModeToggle
          icon={<ClipboardList size={13} />} label="计划"
          on={state.planMode} locked={streaming}
          onClick={() => onStateChange({ ...state, planMode: !state.planMode })}
        />
        <ModeToggle
          icon={<Brain size={13} />} label="思考"
          on={state.thinking} locked={streaming}
          onClick={() => onStateChange({ ...state, thinking: !state.thinking })}
        />
        <ModeToggle
          icon={<Globe size={13} />} label="联网"
          on={state.webSearch} locked={streaming}
          onClick={() => onStateChange({ ...state, webSearch: !state.webSearch })}
        />

        <div className="ml-auto flex items-center gap-2">
          {/* 模型 pill（上下文水位依赖 G3，暂缺） */}
          <span
            className="max-w-[180px] truncate rounded-lg border border-line px-2 py-1 text-[10.5px] font-medium text-ink-dim"
            title={`模型：${agentModel || '默认'}`}
          >
            {agentModel || '默认模型'}
          </span>
          <IconBtn title="语音输入（即将上线）"><Mic size={15} /></IconBtn>

          {streaming ? (
            <button
              onClick={onStop}
              className="flex h-8 items-center gap-1.5 rounded-xl bg-ink px-3.5 text-[11.5px] font-bold text-panel transition-opacity hover:opacity-85"
              title="停止执行"
            >
              <Square size={11} fill="currentColor" /> 停止
            </button>
          ) : (
            <button
              onClick={() => submit()}
              disabled={!text.trim() || disabled}
              className="flex h-8 w-8 flex-none items-center justify-center rounded-xl text-white transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-35"
              style={{ background: 'var(--color-brand)' }}
              title="发送 (Enter)"
            >
              <SendHorizontal size={15} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* 圆形图标按钮：hover 淡紫底 */
function IconBtn({ title, children, disabled = false }: {
  title: string; children: ReactNode; disabled?: boolean;
}) {
  return (
    <button
      title={title}
      disabled={disabled}
      className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-dim transition-colors hover:bg-brand-soft hover:text-brand disabled:opacity-40 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  );
}

/* 模式开关：图标+文字，激活=淡紫底紫字 */
function ModeToggle({ icon, label, on, locked, onClick }: {
  icon: ReactNode; label: string; on: boolean; locked: boolean; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={locked}
      title={locked ? '执行中不可切换' : on ? `关闭${label}` : `开启${label}`}
      className={`flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[11.5px] font-semibold transition-colors ${
        on
          ? 'bg-brand-soft text-brand'
          : 'text-ink-dim hover:bg-brand-soft/50 hover:text-ink-soft'
      } ${locked ? 'cursor-not-allowed opacity-50' : ''}`}
    >
      {icon}
      {label}
    </button>
  );
}
