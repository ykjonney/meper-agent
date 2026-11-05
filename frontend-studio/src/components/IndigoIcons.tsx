/** 靛蓝主题图标库 —— 有机曲线语言（viewBox 16 · stroke 1.3-1.4 · currentColor）。
 *
 *  语义原则：看见图标即知功能（机器人=智能体、清单=任务、节点连线=工作流、
 *  扳手=工具、四角星=技能、插头=MCP、翻开书=知识库、人形=子代理、芯片=模型、
 *  声波=语音、对话泡=会话、四格=资源库）。
 *
 *  分类身份色（soft 底 + 深色 icon，见 design-system §图标）：
 *  工具=靛蓝 · 技能=绿 · MCP=琥珀 · 知识库=赭 · 工作流=紫 · 子代理=灰 · 语音=青
 *  新图标先登记 docs/superpowers/specs/2026-11-03-indigo-design-system.md §6 再实现。 */

interface IconProps { size?: number; className?: string }

/** 会话（对话泡） */
export function IconChat({ size = 14, className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" width={size} height={size} className={className}>
      <path d="M3.2 2.8h9.6a1.7 1.7 0 0 1 1.7 1.7v5a1.7 1.7 0 0 1-1.7 1.7H8.2L5 13.6v-2.4H3.2a1.7 1.7 0 0 1-1.7-1.7v-5a1.7 1.7 0 0 1 1.7-1.7z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
    </svg>
  );
}

/** 智能体（圆角机器人头：脸 + 双眼 + 天线） */
export function IconAgent({ size = 14, className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" width={size} height={size} className={className}>
      <rect x="2.6" y="4.6" width="10.8" height="9" rx="3.4" stroke="currentColor" strokeWidth="1.4"/>
      <circle cx="6" cy="8.6" r=".95" fill="currentColor"/>
      <circle cx="10" cy="8.6" r=".95" fill="currentColor"/>
      <path d="M8 1.4v3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
      <circle cx="8" cy="1.3" r="1" stroke="currentColor" strokeWidth="1.2"/>
    </svg>
  );
}

/** 任务（清单勾选） */
export function IconTask({ size = 14, className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" width={size} height={size} className={className}>
      <rect x="2.2" y="2" width="11.6" height="12" rx="2.6" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M5.4 5.6h5.2M5.4 8.4h5.2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
      <path d="M4.8 11.3l1.1 1.1 2.2-2.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

/** 工作流（三节点曲线连线） */
export function IconFlow({ size = 14, className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" width={size} height={size} className={className}>
      <circle cx="3.4" cy="3.4" r="1.9" stroke="currentColor" strokeWidth="1.4"/>
      <circle cx="12.6" cy="8" r="1.9" stroke="currentColor" strokeWidth="1.4"/>
      <circle cx="3.4" cy="12.6" r="1.9" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M5.1 4.2c3.6 1.6 4.3 2.4 5.8 3.1M5.1 11.8c3.6-1.6 4.3-2.4 5.8-3.1" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    </svg>
  );
}

/** 资源库（四格收纳） */
export function IconResource({ size = 14, className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" width={size} height={size} className={className}>
      <rect x="1.5" y="1.5" width="5.5" height="5.5" rx="1.8" stroke="currentColor" strokeWidth="1.4"/>
      <rect x="9" y="1.5" width="5.5" height="5.5" rx="1.8" stroke="currentColor" strokeWidth="1.4"/>
      <rect x="1.5" y="9" width="5.5" height="5.5" rx="1.8" stroke="currentColor" strokeWidth="1.4"/>
      <rect x="9" y="9" width="5.5" height="5.5" rx="1.8" stroke="currentColor" strokeWidth="1.4"/>
    </svg>
  );
}

/** 内置工具（曲线扳手） */
export function IconWrench({ size = 14, className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" width={size} height={size} className={className}>
      <path d="M10.8 2.2a3.6 3.6 0 0 0-4.3 4.6L2.6 10.7a1.7 1.7 0 1 0 2.4 2.4l3.9-3.9a3.6 3.6 0 0 0 4.6-4.3L11 7.4 8.4 4.8z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
    </svg>
  );
}

/** 技能（曲线四角星 · 能力闪光） */
export function IconSkill({ size = 14, className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" width={size} height={size} className={className}>
      <path d="M8 1.8c.6 3.4 2.8 5.6 6.2 6.2-3.4.6-5.6 2.8-6.2 6.2-.6-3.4-2.8-5.6-6.2-6.2 3.4-.6 5.6-2.8 6.2-6.2z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
    </svg>
  );
}

/** MCP 连接（插头） */
export function IconPlug({ size = 14, className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" width={size} height={size} className={className}>
      <path d="M5.6 1.6v3.2M10.4 1.6v3.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
      <path d="M4 5h8v3a4 4 0 0 1-8 0z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
      <path d="M8 12v2.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  );
}

/** 知识库（翻开书） */
export function IconBook({ size = 14, className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" width={size} height={size} className={className}>
      <path d="M2 3c2.5-1.4 5-1.4 6 0 1-1.4 3.5-1.4 6 0v9c-2.5 1.4-5 1.4-6 0-1 1.4-3.5 1.4-6 0z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
      <path d="M8 3v9" stroke="currentColor" strokeWidth="1.3"/>
    </svg>
  );
}

/** 可委派子 Agent（人形） */
export function IconSubAgent({ size = 14, className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" width={size} height={size} className={className}>
      <circle cx="8" cy="5" r="2.8" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M2.5 13.5c.8-2.6 3-4 5.5-4s4.7 1.4 5.5 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  );
}

/** 模型（芯片） */
export function IconChip({ size = 14, className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" width={size} height={size} className={className}>
      <rect x="4" y="4" width="8" height="8" rx="2" stroke="currentColor" strokeWidth="1.4"/>
      <rect x="6.6" y="6.6" width="2.8" height="2.8" stroke="currentColor" strokeWidth="1.2"/>
      <path d="M8 1.4v2.2M8 12.4v2.2M1.4 8h2.2M12.4 8h2.2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    </svg>
  );
}

/** 语音（声波弧） */
export function IconVoice({ size = 14, className }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" fill="none" width={size} height={size} className={className}>
      <path d="M4.5 5.8v4.4M8 3.4v9.2M11.5 5.8v4.4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  );
}
