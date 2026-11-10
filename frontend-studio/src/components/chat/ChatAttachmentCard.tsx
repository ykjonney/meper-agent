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
import { downloadAttachment, fetchAttachmentBlob } from './message-utils';

export function ChatAttachmentCard({
  att,
  sessionId,
}: {
  att: ChatAttachment;
  sessionId: string | null;
}) {
  const kind = detectPreviewKind(att.name, att.mime_type);
  const isImage = kind === 'image';

  // 图片缩略图 blob（懒加载，卸载时回收 objectURL）
  const [thumbUrl, setThumbUrl] = useState<string>();
  const [thumbError, setThumbError] = useState(false);
  const [loadingThumb, setLoadingThumb] = useState(isImage);

  // 弹窗预览态：打开时按需拉取并按类型喂给 FilePreviewModal
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewText, setPreviewText] = useState<string>();
  const [previewImageUrl, setPreviewImageUrl] = useState<string>();

  // 图片缩略图：挂载即拉一次（output 图片同样从 blob 取）
  useEffect(() => {
    if (!isImage) return;
    let url: string | undefined;
    let cancelled = false;
    (async () => {
      try {
        const blob = await fetchAttachmentBlob(att, sessionId);
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setThumbUrl(url);
      } catch {
        if (!cancelled) setThumbError(true);
      } finally {
        if (!cancelled) setLoadingThumb(false);
      }
    })();
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [att, sessionId, isImage]);

  // 打开弹窗预览：按 detectPreviewKind 决定喂 text 还是 imageUrl；二进制直接走下载
  const openPreview = async () => {
    if (kind === 'binary') {
      // 不可预览：直接下载
      try {
        await downloadAttachment(att, sessionId);
      } catch {
        /* ignore */
      }
      return;
    }
    setPreviewOpen(true);
    setPreviewLoading(true);
    try {
      const blob = await fetchAttachmentBlob(att, sessionId);
      if (kind === 'image') {
        setPreviewImageUrl(URL.createObjectURL(blob));
        setPreviewText(undefined);
      } else {
        setPreviewText(await blob.text());
        setPreviewImageUrl(undefined);
      }
    } catch {
      // 拉取失败：留空，FilePreview 会渲染占位
    } finally {
      setPreviewLoading(false);
    }
  };

  // 关闭弹窗时回收 imageUrl（text 不需要回收）
  const closePreview = () => {
    if (previewImageUrl) URL.revokeObjectURL(previewImageUrl);
    setPreviewImageUrl(undefined);
    setPreviewText(undefined);
    setPreviewOpen(false);
  };

  // ── 图片：缩略图直显（可点击放大） ──
  if (isImage) {
    return (
      <>
        <button
          type="button"
          onClick={openPreview}
          className="relative rounded-lg overflow-hidden border border-line bg-page hover:border-brand transition-colors cursor-pointer block"
          title={att.name}
        >
          {loadingThumb ? (
            <div className="w-48 h-32 flex items-center justify-center text-ink-dim">
              <Loader2 className="w-4 h-4 animate-spin" />
            </div>
          ) : thumbError ? (
            <div className="w-48 h-32 flex flex-col items-center justify-center text-ink-dim gap-1 px-2">
              <ImageIcon className="w-5 h-5" />
              <span className="text-[11px] truncate max-w-full">{att.name}</span>
            </div>
          ) : (
            thumbUrl && (
              <img
                src={thumbUrl}
                alt={att.name}
                // 固定尺寸 + cover:与 loading/error 占位(w-48 h-32)一致,
                // 竖图/横图/多图排列整齐无跳动,点击弹窗看原图(不裁剪)。
                className="w-48 h-32 object-cover block"
                draggable={false}
              />
            )
          )}
        </button>
        <FilePreviewModal
          open={previewOpen}
          filename={att.name}
          mime={att.mime_type}
          imageUrl={previewImageUrl}
          text={previewText}
          onClose={closePreview}
          onDownload={() => downloadAttachment(att, sessionId)}
        />
      </>
    );
  }

  // ── 非图片：文件卡片（名称 + 类型徽标 + 预览/下载） ──
  return (
    <>
      <div className="flex items-center gap-3 w-fit max-w-full pl-3 pr-2 py-2.5 rounded-[10px] bg-page transition-colors group">
        <div className="w-[34px] h-[34px] rounded-lg bg-raise flex items-center justify-center shrink-0">
          <FileText className="w-4 h-4 text-ink-dim" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-ink truncate" title={att.name}>
            {att.name}
          </p>
          <p className="text-[11px] text-ink-dim font-mono uppercase">
            {att.mime_type || kind}
            {att.size ? ` · ${formatFileSize(att.size)}` : ''}
          </p>
        </div>
        {kind === 'binary' ? (
          <button
            type="button"
            onClick={() => downloadAttachment(att, sessionId)}
            title="下载"
            className="p-1.5 text-ink-dim hover:text-brand cursor-pointer transition-colors shrink-0"
          >
            <Download className="w-3.5 h-3.5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={openPreview}
            title="预览"
            className="p-1.5 text-ink-dim hover:text-brand cursor-pointer transition-colors shrink-0"
          >
            <FileCode className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      <FilePreviewModal
        open={previewOpen}
        filename={att.name}
        mime={att.mime_type}
        text={previewText}
        imageUrl={previewImageUrl}
        onClose={closePreview}
        onDownload={() => downloadAttachment(att, sessionId)}
      />
      {previewLoading && previewOpen && null}
    </>
  );
}

