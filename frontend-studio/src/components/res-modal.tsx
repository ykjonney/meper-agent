/**
 * res-modal.tsx — 资源创建/编辑弹窗共享骨架（设计稿 resource-create-edit.html）。
 *
 * 统一形态：类别色徽章 + 标题 + mono kicker + 下划线字段（fld）+ 类型卡 /
 * 厂商格 / 分段控件 + foot（note 左、操作右）。五类资源弹窗共用，避免各写一套。
 */
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';

/** 弹窗壳：徽章 + 标题 + kicker + 内容 + foot */
export function ResModal({
  badge, badgeCls, title, kicker, onClose, children, footer, width = 520, formId, fixedHeight, smooth,
}: {
  badge: ReactNode;
  /** 徽章配色（soft 底 + 深色 icon），如知识库赭色「bg-[#F5E9E2] text-cat-kb」 */
  badgeCls: string;
  title: string;
  /** mono kicker，如「KNOWLEDGE BASE · CREATE」 */
  kicker: string;
  onClose: () => void;
  children: ReactNode;
  /** foot：note 文案 + 操作按钮组（提交按钮加 form={formId} 关联 children 内表单） */
  footer?: { note?: string; actions: ReactNode };
  width?: number;
  /** children 内 <form> 的 id——footer 位于 form 外，提交按钮需声明 form={formId} 才能触发提交 */
  formId?: string;
  /** 恒定高度（宽高全固定）：内容在固定框内伸缩/滚动，任何状态切换零尺寸变化零抖动 */
  fixedHeight?: number;
  /** 高度平滑跟随内容：宽度恒定，高度经 ResizeObserver 测量 + 200ms 过渡（不跳变不拉扯） */
  smooth?: boolean;
}) {
  // smooth 模式：测内容自然高 → 弹窗高度平滑跟随（宽度恒定，仅高度方向变化）。
  // ResizeObserver 必须观察「内容包裹层」——观察被 flex 固定高的滚动容器时，
  // 内容变化不改变其盒子尺寸，observer 不触发，高度卡住导致内部滚动。
  const bodyRef = useRef<HTMLDivElement>(null)
  const innerRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const extraRef = useRef(0)
  const [h, setH] = useState<number | undefined>(undefined)
  useLayoutEffect(() => {
    if (!smooth) return
    const body = bodyRef.current
    const inner = innerRef.current
    const content = contentRef.current
    if (!body || !inner || !content) return
    // 首次（未限高，自然布局）：记录头部/kicker/footer 等固定件高度
    extraRef.current = Math.max(0, body.offsetHeight - inner.offsetHeight)
    const measure = () => {
      const need = content.offsetHeight + extraRef.current
      setH(Math.min(need, window.innerHeight * 0.9))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(content)
    return () => ro.disconnect()
  }, [smooth])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        ref={bodyRef}
        onClick={(e) => e.stopPropagation()}
        style={{ width, ...(smooth && h ? { height: h } : fixedHeight ? { width, height: fixedHeight } : {}) }}
        className={fixedHeight
          ? 'flex flex-col overflow-hidden bg-panel rounded-2xl shadow-[var(--shadow-pop)] px-[30px] pt-[26px] pb-5'
          : smooth
            ? 'flex flex-col overflow-hidden bg-panel rounded-2xl shadow-[var(--shadow-pop)] px-[30px] pt-[26px] pb-5 transition-[height] duration-200 ease-out'
            : 'min-h-[420px] max-h-[90vh] flex flex-col overflow-y-auto overflow-x-hidden scrollbar-custom bg-panel rounded-2xl shadow-[var(--shadow-pop)] px-[30px] pt-[26px] pb-6'}
      >
        {/* 头部：徽章 + 标题 + 关闭 */}
        <div className="flex items-center gap-2.5">
          <div className={`w-[34px] h-[34px] rounded-[10px] flex items-center justify-center shrink-0 ${badgeCls}`}>
            {badge}
          </div>
          <h2 className="text-[16px] font-extrabold text-ink tracking-[-0.01em]">{title}</h2>
          <button
            onClick={onClose}
            className="ml-auto text-ink-faint hover:text-ink text-[16px] leading-none cursor-pointer"
            title="关闭"
          >×</button>
        </div>
        <div className="font-mono text-[10.5px] text-ink-faint mt-1 ml-[44px] mb-[22px]">{kicker}</div>

        {/* 内容区：smooth 模式测量此区自然高 → 弹窗高度平滑跟随；footer 恒在底部 */}
        <div ref={innerRef} className={`flex-1 min-h-0 ${fixedHeight || smooth ? 'overflow-y-auto overflow-x-hidden scrollbar-custom -mx-[30px] px-[30px]' : ''}`}>
          <div ref={contentRef}>{children}</div>
        </div>

        {footer && (
          <div className="flex items-center mt-4 pt-4 border-t border-line shrink-0">
            {footer.note && <span className="text-[10.5px] text-ink-faint">{footer.note}</span>}
            <div className="ml-auto flex items-center gap-2.5">{footer.actions}</div>
          </div>
        )}
      </div>
    </div>
  );
}

/** 下划线字段：label（必填靛蓝 * / 可选灰）+ 子元素（UInput / TypeCards / Seg…）+ hint */
export function Field({ label, required, optional, hint, children }: {
  label: string;
  required?: boolean;
  optional?: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="mb-[18px]">
      <div className="flex items-baseline gap-1.5 text-[11.5px] font-semibold text-ink-dim mb-1">
        {label}
        {required && <span className="text-brand">*</span>}
        {optional && <span className="text-ink-faint font-medium">{optional}</span>}
      </div>
      {children}
      {hint && <div className="text-[10.5px] text-ink-faint mt-1.5 leading-[1.6]">{hint}</div>}
    </div>
  );
}

/** 下划线输入：无边框 + 底线（focus 靛蓝）——设计稿 fld input */
export function UInput({ mono, ...rest }: React.InputHTMLAttributes<HTMLInputElement> & { mono?: boolean }) {
  return (
    <input
      {...rest}
      className={`w-full border-0 border-b border-line-strong bg-transparent px-0 py-[7px] text-[13px] text-ink placeholder:text-ink-faint outline-none transition-colors focus:border-b-brand ${mono ? 'font-mono text-[12.5px]' : ''}`}
    />
  );
}

/** 下划线多行输入 */
export function UTextarea({ mono, ...rest }: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { mono?: boolean }) {
  return (
    <textarea
      {...rest}
      className={`w-full border-0 border-b border-line-strong bg-transparent px-0 py-[7px] text-[13px] text-ink placeholder:text-ink-faint outline-none transition-colors focus:border-b-brand resize-none ${mono ? 'font-mono text-[12.5px]' : ''}`}
    />
  );
}

/** 分段控件：raise 容器 + 选中白块靛蓝字 */
export function Seg<T extends string>({ value, onChange, options, maxW, className }: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  maxW?: number;
  className?: string;
}) {
  return (
    <div className={`inline-flex max-w-full bg-raise rounded-[9px] p-[3px] ${className ?? ''}`} style={maxW ? { maxWidth: maxW } : undefined}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`flex-1 whitespace-nowrap border-0 px-3 py-[7px] rounded-[7px] text-xs cursor-pointer transition-colors ${
            value === o.value ? 'bg-panel text-brand font-bold shadow-[0_1px_2px_rgba(0,0,0,.06)]' : 'bg-transparent text-ink-dim hover:text-ink'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** 类型卡：1.5px 边 + 选中 brand 边 + soft 底；22px 图标块 + 标题 + 描述 */
export function TypeCard({ on, icon, iconCls, title, desc, onClick }: {
  on: boolean;
  icon: ReactNode;
  iconCls: string;
  title: string;
  desc: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-left border-[1.5px] rounded-xl p-3.5 cursor-pointer transition-colors ${
        on ? 'border-brand bg-brand-soft/50' : 'border-line hover:border-line-strong'
      }`}
    >
      <div className="flex items-center gap-[7px] text-[13px] font-bold text-ink">
        <span className={`w-[22px] h-[22px] rounded-[7px] flex items-center justify-center shrink-0 ${iconCls}`}>{icon}</span>
        {title}
      </div>
      <div className="text-[11px] text-ink-faint mt-1.5 leading-[1.55]">{desc}</div>
    </button>
  );
}

/** 厂商格：方形圆角块（实色底白字），选中 brand 外圈 */
export function VendorCell({ on, bg, fg = '#fff', label, title, onClick }: {
  on: boolean;
  bg: string;
  /** 文字/线条色：白底厂商格传深色 */
  fg?: string;
  label: ReactNode;
  title: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={`aspect-square rounded-[11px] flex items-center justify-center cursor-pointer transition-shadow font-bold border ${on ? 'ring-2 ring-brand' : 'hover:opacity-90'}`}
      style={{ background: bg, color: fg, borderColor: fg === '#fff' ? 'transparent' : 'var(--color-line)' }}
    >
      {label}
    </button>
  );
}
