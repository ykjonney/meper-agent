import { type RefObject } from 'react';
import { X } from 'lucide-react';
import { SessionFilesPanel, type SessionFilesPanelHandle } from '../SessionFilesPanel';

interface ArtifactsPanelProps {
  rootRef: RefObject<HTMLDivElement | null>;
  startColDrag: (e: React.MouseEvent, onMove: (clientX: number) => void) => void;
  setPanelW: (w: number) => void;
  artifactCount: number;
  onClose: () => void;
  filesPanelRef: RefObject<SessionFilesPanelHandle | null>;
  activeSessionId: string | null;
}

/** 4. RIGHT PANEL：产物 + 后续扩展功能（左右可拉伸，默认关闭，≥lg 显示） */
export function ArtifactsPanel({
  rootRef, startColDrag, setPanelW, artifactCount, onClose, filesPanelRef, activeSessionId,
}: ArtifactsPanelProps) {
  return (
    <div
      style={{ width: 'var(--panel-w)' }}
      className="hidden lg:flex min-h-0 shrink-0 border-l border-line bg-well flex-col relative"
    >
      {/* 左缘拖拽手标 */}
      <div
        onMouseDown={(e) => {
          const rect = rootRef.current?.getBoundingClientRect();
          if (!rect) return;
          startColDrag(e, (x) => {
            const w = clamp(rect.right - x, 280, 560);
            setPanelW(w);
            localStorage.setItem('agentflow_chat_panel_w', String(w));
          });
        }}
        className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-brand/40 transition-colors z-10"
        title="拖拽调整宽度"
      />
      <div className="h-12 shrink-0 flex items-center gap-2 px-4 border-b border-line">
        <span className="af-label">产物</span>
        {artifactCount > 0 && (
          <span className="px-[7px] rounded-full text-[11px] font-mono leading-[17px] bg-raise text-ink-dim">
            {artifactCount}
          </span>
        )}
        <button
          onClick={onClose}
          className="ml-auto w-6 h-6 rounded-md flex items-center justify-center text-ink-dim hover:text-ink hover:bg-raise transition cursor-pointer"
          title="关闭功能区"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-custom">
        <SessionFilesPanel ref={filesPanelRef} sessionId={activeSessionId} />
      </div>
    </div>
  );
}

function clamp(v: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v));
}
