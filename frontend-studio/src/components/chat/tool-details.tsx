import { useState, useRef, useEffect, useLayoutEffect, useMemo, Fragment, FormEvent, useCallback, type MouseEvent, type ChangeEvent, type ReactNode } from 'react';
import { Agent, Message, type ChatAttachment, type TimelineEntry } from '../../types'
import {
  Send, Plus, Trash2, FileCode, CheckCircle, Check,
  Bot, Terminal, Loader2, Paperclip, Brain, X, ClipboardList, ShieldAlert,
  Wrench, AlertTriangle, ChevronRight, ChevronDown, User, Download, FileText, Image as ImageIcon, Mic, Copy, RotateCcw,
  PenLine, SquarePen, FolderSearch, Search, Globe, Link2, BarChart3, FileSearch, BookOpen,
  ThumbsUp, ThumbsDown, PanelRight, Workflow,
  FolderOpen, LayoutDashboard, Shield, ArrowLeftRight, Key,
} from 'lucide-react';
import { toast } from '../ui/toast'
import { IconAgent, IconTask, IconFlow, IconResource } from '../IndigoIcons'
import { NotificationCenter } from '../notification-center'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { Popover } from '../ui'
import { userSkillsApi, type SessionFeedbackItem } from '../../services/user-skills-api'
import {
  sessionApi, sessionKeys, type Session, type MessageRecord, type FileRef, getFileId,
} from '../../services/session-api';
import { agentApi, agentKeys, type DoneTimelineEntry, type ThinkingLevel } from '../../services/agent-api'
import { modelApi, modelKeys } from '../../services/model-api'
import { toStudioAgent } from '../../services/adapters'
import { getFileBlob, downloadFile as downloadFileById } from '../../services/file-api'
import { parseSSEStream } from '../../lib/sse-parser'
import { formatFileSize } from '../../lib/file-preview'
import { formatTimeFull } from '../../lib/formatTime'
import { isImeComposing } from '../../lib/keyboard'
import { countZi, truncateByZi } from '../../lib/text-stats'
import { SessionFilesPanel, type SessionFilesPanelHandle } from '../SessionFilesPanel'
import AvatarRender from '../AvatarRender'
import { Markdown } from '../Markdown'
import { detectPreviewKind } from '../FilePreview'
import { FilePreviewModal } from '../FilePreviewModal'
import { WorkflowTaskCard, parseTaskCreated } from '../WorkflowTaskCard'
import WorkflowProposalCard from '../workflow-proposal-card'
import {
  ClarificationFormCard,
  DISMISSED_CLARIFICATION_TEXT,
  type ClarificationField,
} from '../clarification-form-card';
import { ChatVoiceComposer } from '../voice/ChatVoiceComposer'
import { voiceConfigApi, voiceConfigKeys } from '../../services/voice-config-api'

// 思考档位元数据：label=档位文字，color=强度色（信号色 token，明暗主题自适应；
// off=灰 / low=绿 / medium=黄 / high=橙红）。
import { ThinkingEntryCard } from './ToolEntryCard';

export const TOOL_STATUS_CFG: Record<
  NonNullable<Message['toolStatus']>,
  { wrap: string; hover: string; icon: string; label: string }
> = {
  // 活动卡统一 page 底（与消息背景同色，演示稿 §6.2 执行活动卡）；
  // 彩色只落在状态图标/文字上：等待琥珀 / 成功灰 / 失败红。
  pending: {
    wrap: 'bg-page border-line',
    hover: 'hover:bg-raise',
    icon: 'text-sig-wait',
    label: '正在生成参数',
  },
  running: {
    wrap: 'bg-page border-line',
    hover: 'hover:bg-raise',
    icon: 'text-sig-wait',
    label: '执行中…',
  },
  success: {
    wrap: 'bg-page border-line',
    hover: 'hover:bg-raise',
    icon: 'text-ink-dim',
    label: '已完成',
  },
  error: {
    wrap: 'bg-page border-line',
    hover: 'hover:bg-raise',
    icon: 'text-sig-fail',
    label: '失败',
  },
};

/** Pretty-print a tool's request args. Falls back to String() on failure. */
export function formatToolArgs(args?: Record<string, unknown>): string {
  if (!args || Object.keys(args).length === 0) return '';
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

/** Try to pretty-print a tool result. If it parses as JSON, re-serialize it
 *  indented; otherwise return the raw string. */
/** 工具执行耗时格式化（ms → 人类可读）。 */
export function formatToolDuration(ms: number): string {
  if (!ms || ms < 0) return '';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const sec = Math.round((ms % 60_000) / 1000);
  return `${m}m ${sec}s`;
}

/**
 * 工具详情的人性化结构：不同工具展示不同内容，而非裸 args JSON。
 * - bash        → 终端命令原文（保留换行，等宽渲染）
 * - edit        → 增删差异（old 红 / new 绿，逐行对照）
 * - write       → 写入的内容（等宽展示）
 * - read        → 无参数区（路径已在摘要行，详情直接展示 result）
 * - render_chart→ 无参数区（图表已在正文 EChartBlock 渲染）
 * - 默认        → JSON pretty（兜底）
 */
export type ToolDetailKind = 'command' | 'diff' | 'code' | 'json' | 'none';
export function toolDetail(entry: TimelineEntry): { kind: ToolDetailKind; payload: string; diffOld?: string; diffNew?: string } {
  const args = (entry.args ?? {}) as Record<string, unknown>;
  const name = entry.toolName ?? '';
  const str = (v: unknown) => (v == null ? '' : String(v));
  if (name === 'bash' || name === 'run_command' || name === 'execute')
    return { kind: 'command', payload: str(args.command ?? args.cmd ?? args.script) };
  if (name === 'edit_file' || name === 'edit' || name === 'apply_patch')
    return {
      kind: 'diff',
      payload: str(args.path ?? args.file_path ?? args.file),
      diffOld: str(args.old_string ?? args.old_text ?? args.original),
      diffNew: str(args.new_string ?? args.new_text ?? args.updated),
    };
  if (name === 'write_file' || name === 'write' || name === 'create_file')
    return { kind: 'code', payload: str(args.content ?? args.text ?? '') };
  if (name === 'read_file' || name === 'read' || name === 'render_chart')
    return { kind: 'none', payload: '' };
  try {
    return { kind: 'json', payload: JSON.stringify(args, null, 2) };
  } catch {
    return { kind: 'none', payload: '' };
  }
}

export function formatToolResult(raw?: string): { text: string; isJson: boolean } {
  if (!raw) return { text: '', isJson: false };
  const trimmed = raw.trim();
  if (!(trimmed.startsWith('{') || trimmed.startsWith('['))) {
    return { text: raw, isJson: false };
  }
  try {
    return { text: JSON.stringify(JSON.parse(trimmed), null, 2), isJson: true };
  } catch {
    return { text: raw, isJson: false };
  }
}

export const RESULT_COLLAPSE_THRESHOLD = 800;

/** 流式执行中三点跳动（消息级动效）。与 ThinkingEntryCard 头部圆点同款
 *  （animate-thinking-dot + 0.18s stagger），对齐 client streaming-dots：
 *  放在消息末尾、不碰 markdown 内部，稳定不抖。 */
export function toolSummary(entry: TimelineEntry): { verb: string; detail: string } {
  const args = (entry.args ?? {}) as Record<string, unknown>;
  const name = entry.toolName ?? '';
  const str = (v: unknown) => (v == null ? '' : String(v));
  const pick = (...keys: string[]) => {
    for (const k of keys) if (args[k] != null && String(args[k])) return String(args[k]);
    return '';
  };
  if (name === 'bash' || name === 'run_command' || name === 'execute') {
    // 多行命令（heredoc 等）压平为单行示意：截断交给摘要行 CSS truncate
    // （到行尾才出省略号，而非 JS 首行截断），完整命令在详情里
    const cmd = pick('command', 'cmd', 'script').replace(/\s*\n\s*/g, ' ').trim();
    return { verb: '执行命令', detail: cmd };
  }
  if (name === 'read_file' || name === 'read')
    return { verb: '读取文件', detail: pick('path', 'file_path', 'file_id', 'file') };
  if (name === 'write_file' || name === 'write' || name === 'create_file')
    return { verb: '写入文件', detail: pick('path', 'file_path', 'file') };
  if (name === 'edit_file' || name === 'edit' || name === 'apply_patch')
    return { verb: '编辑文件', detail: pick('path', 'file_path', 'file') };
  if (name === 'glob' || name === 'list_files' || name === 'list_dir')
    return { verb: '查找文件', detail: pick('pattern', 'path', 'dir') };
  if (name === 'grep' || name === 'search_content')
    return { verb: '搜索内容', detail: pick('pattern', 'query', 'keyword') };
  if (name === 'web_search' || name === 'search_web')
    return { verb: '搜索网页', detail: pick('query', 'keyword', 'q') };
  if (name === 'fetch_url' || name === 'open_url')
    return { verb: '访问网页', detail: pick('url', 'link') };
  if (name === 'render_chart')
    return { verb: '生成图表', detail: pick('title', 'chart_type') };
  if (name === 'parse_file')
    return { verb: '解析文件', detail: pick('path', 'file_id', 'file') };
  if (name === 'load_skill' || name === 'load_skills')
    return { verb: '加载技能', detail: pick('skill_name', 'name', 'skill') };
  if (name === 'delegate_to_subagent')
    return { verb: '委派子任务', detail: pick('subagent_name', 'task') };
  if (name === 'propose_plan')
    return { verb: '提交执行计划', detail: '' };
  if (name === 'dispatch_workflow')
    return { verb: '调度工作流', detail: pick('workflow_name', 'workflow_id') };
  if (name === 'ask_clarification')
    return { verb: '发起澄清', detail: '' };
  return { verb: name || '调用工具', detail: '' };
}

/** 工具类型图标：终态摘要行左侧的类型标识（运行中统一转圈）。 */
export function ToolTypeIcon({ toolName, className }: { toolName?: string; className?: string }) {
  const name = toolName ?? '';
  const cls = className ?? 'w-3.5 h-3.5';
  if (name === 'bash' || name === 'run_command' || name === 'execute')
    return <Terminal className={cls} />;
  if (name === 'read_file' || name === 'read')
    return <FileText className={cls} />;
  if (name === 'write_file' || name === 'write' || name === 'create_file')
    return <PenLine className={cls} />;
  if (name === 'edit_file' || name === 'edit' || name === 'apply_patch')
    return <SquarePen className={cls} />;
  if (name === 'glob' || name === 'list_files' || name === 'list_dir')
    return <FolderSearch className={cls} />;
  if (name === 'grep' || name === 'search_content')
    return <Search className={cls} />;
  if (name === 'web_search' || name === 'search_web')
    return <Globe className={cls} />;
  if (name === 'fetch_url' || name === 'open_url')
    return <Link2 className={cls} />;
  if (name === 'render_chart')
    return <BarChart3 className={cls} />;
  if (name === 'parse_file')
    return <FileSearch className={cls} />;
  if (name === 'load_skill' || name === 'load_skills')
    return <BookOpen className={cls} />;
  if (name === 'delegate_to_subagent')
    return <Bot className={cls} />;
  if (name === 'propose_plan')
    return <ClipboardList className={cls} />;
  if (name === 'dispatch_workflow')
    return <Workflow className={cls} />;
  return <Wrench className={cls} />;
}

/** 判断 tool entry 是否为"需要用户交互"的卡片——交互卡打断执行过程分组。 */
export function isInteractiveTool(entry: TimelineEntry): boolean {
  return ['ask_clarification', 'propose_plan', 'confirm_workflow'].includes(
    entry.toolName ?? '',
  );
}

/**
 * ParallelToolBatch — 同一批并行执行的工具调用（紧邻的普通 tool entries）
 * 合并为一个折叠条目：「并行执行 N 个命令」。
 * - 任一命令运行中 → 自动展开（明细可见、执行中命令转圈）
 * - 全部完成 → 自动收起为计数行
 */
export function mergeToolRuns(entries: TimelineEntry[]): { entry: TimelineEntry; count: number; isTool: boolean }[] {
  const items: { entry: TimelineEntry; count: number; isTool: boolean }[] = [];
  for (const entry of entries) {
    // 只合并相邻同类工具（同 toolName + 同摘要）；thinking/text/error 原样保留
    if (entry.type === 'tool') {
      const sum = toolSummary(entry);
      const last = items[items.length - 1];
      if (
        last &&
        last.isTool &&
        last.entry.toolName === entry.toolName &&
        toolSummary(last.entry).detail === sum.detail
      ) {
        last.count += 1;
        continue;
      }
      items.push({ entry, count: 1, isTool: true });
    } else {
      items.push({ entry, count: 1, isTool: false });
    }
  }
  return items;
}

export function parsePlanSections(plan: string): Array<{ title: string; body: string }> {
  const lines = plan.split("\n");
  const sections: Array<{ title: string; body: string }> = [];
  let current: { title: string; body: string } | null = null;
  for (const line of lines) {
    const m = /^#\s+(.*)$/.exec(line);
    if (m) {
      if (current) sections.push(current);
      current = { title: m[1].trim(), body: "" };
    } else {
      if (!current) current = { title: "", body: "" };
      current.body += line + "\n";
    }
  }
  if (current) sections.push(current);
  return sections.filter((sec) => sec.title || sec.body.trim());
}

/** 步骤 checkbox 转 Unicode 字形（Markdown 任务列表渲染不可依赖）。 */
export function planCheckboxGlyphs(body: string): string {
  return body
    .replace(/^- \[ \]\s*/gm, "☐ ")
    .replace(/^- \[x\]\s*/gim, "☑ ");
}

export const PLAN_SECTION_ORDER = ["目标", "背景与约束", "步骤", "验收标准", "完成时交付"];

