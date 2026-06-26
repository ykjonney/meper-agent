/**
 * SessionFilesPanel — generated-file manager for a chat session.
 *
 * Ported from the legacy chat-panel "生成文件" surface (chat-panel.tsx:1214-1299).
 * Lists a session's output files with preview / download / delete / ZIP-download.
 * Uses sessionApi (listFiles / previewFile / downloadFile / deleteFile /
 * getZipDownloadUrl) — no backend changes.
 *
 * Parent (ChatHomepage) mounts this when the "文件" tab is active and calls
 * `refresh()` after a stream finishes.
 */
import { useState, useEffect, useImperativeHandle, forwardRef, useCallback } from 'react';
import { FileText, Download, Trash2, Eye, Loader2, FolderArchive } from 'lucide-react';
import {
  sessionApi, type SessionFileEntry,
} from '../services/session-api';
import { detectPreviewKind } from './FilePreview';
import { FilePreviewModal } from './FilePreviewModal';

/** Format bytes → B/KB/MB/GB (ported from legacy formatFileSize). */
function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const val = bytes / Math.pow(1024, i);
  return `${val < 10 ? val.toFixed(1) : Math.round(val)} ${units[i]}`;
}

export interface SessionFilesPanelHandle {
  refresh: () => void;
}

interface PreviewState {
  path: string;
  text?: string;      // text content (md/html/json/txt)
  imageUrl?: string;  // image dataURL
  mime?: string;      // original content-type for render dispatch
}

interface Props {
  sessionId: string | null;
}

export const SessionFilesPanel = forwardRef<SessionFilesPanelHandle, Props>(
  function SessionFilesPanel({ sessionId }, ref) {
    const [files, setFiles] = useState<SessionFileEntry[]>([]);
    const [loading, setLoading] = useState(false);
    const [preview, setPreview] = useState<PreviewState | null>(null);
    const [confirmingPath, setConfirmingPath] = useState<string | null>(null);
    const [busyPath, setBusyPath] = useState<string | null>(null);

    const refresh = useCallback(async () => {
      if (!sessionId) {
        setFiles([]);
        return;
      }
      setLoading(true);
      try {
        setFiles(await sessionApi.listFiles(sessionId));
      } catch {
        setFiles([]);
      } finally {
        setLoading(false);
      }
    }, [sessionId]);

    useImperativeHandle(ref, () => ({ refresh }), [refresh]);

    // Reload whenever the active session changes.
    useEffect(() => {
      setPreview(null);
      setConfirmingPath(null);
      refresh();
    }, [sessionId, refresh]);

    const handlePreview = async (filePath: string) => {
      if (!sessionId) return;
      setBusyPath(filePath);
      try {
        const { blob, contentType } = await sessionApi.previewFile(sessionId, filePath);
        const name = fileName(filePath);
        const kind = detectPreviewKind(name, contentType);

        if (kind === 'image') {
          const dataURL = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result as string);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
          });
          setPreview({ path: filePath, imageUrl: dataURL, mime: contentType });
        } else if (kind === 'binary') {
          // 二进制不可预览，直接下载
          await sessionApi.downloadFile(sessionId, filePath);
        } else {
          // md / html / json / text → 拉文本交给 FilePreview 渲染
          setPreview({ path: filePath, text: await blob.text(), mime: contentType });
        }
      } catch (err) {
        console.error('预览文件失败', err);
      } finally {
        setBusyPath(null);
      }
    };

    const handleDownload = async (filePath: string) => {
      if (!sessionId) return;
      setBusyPath(filePath);
      try {
        await sessionApi.downloadFile(sessionId, filePath);
      } catch (err) {
        console.error('下载文件失败', err);
      } finally {
        setBusyPath(null);
      }
    };

    const handleDownloadZip = () => {
      if (!sessionId) return;
      window.open(sessionApi.getZipDownloadUrl(sessionId), '_blank');
    };

    const handleDelete = async (filePath: string) => {
      if (!sessionId) return;
      setBusyPath(filePath);
      try {
        const updated = await sessionApi.deleteFile(sessionId, filePath);
        setFiles(updated);
        setConfirmingPath(null);
      } catch (err) {
        console.error('删除文件失败', err);
      } finally {
        setBusyPath(null);
      }
    };

    const fileName = (p: string) => p.split('/').pop() || p;

    return (
      <div className="flex-1 overflow-y-auto scrollbar-custom p-6 space-y-3">
        {/* Header: title + ZIP download */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <FileText className="w-3.5 h-3.5 text-[#71717a]" />
            <span className="text-xs font-bold text-white">生成文件</span>
            {files.length > 0 && (
              <span className="text-[10px] text-[#71717a]">({files.length})</span>
            )}
          </div>
          {files.length > 0 && (
            <button
              onClick={handleDownloadZip}
              className="flex items-center gap-1 px-2 py-1 rounded-md border border-[#27272a] hover:bg-[#27272a] text-[#a1a1aa] hover:text-white text-[11px] font-semibold transition cursor-pointer"
            >
              <FolderArchive className="w-3 h-3" /> 下载全部 (ZIP)
            </button>
          )}
        </div>

        {!sessionId && (
          <div className="text-center py-10 text-[11px] text-[#71717a]">请先选择一个会话</div>
        )}

        {loading && (
          <div className="flex items-center justify-center py-8 text-[#71717a]">
            <Loader2 className="w-4 h-4 animate-spin mr-2" /> 载入文件…
          </div>
        )}

        {!loading && sessionId && files.length === 0 && (
          <div className="text-center py-10 text-[11px] text-[#71717a]">暂无生成文件</div>
        )}

        {!loading && files.length > 0 && (
          <div className="space-y-1">
            {files.map((file) => {
              const isBusy = busyPath === file.path;
              const isConfirming = confirmingPath === file.path;
              return (
                <div
                  key={file.path}
                  title={file.path}
                  className="group flex items-center gap-2 rounded-md px-2 py-2 text-[11px] text-[#d4d4d8] hover:bg-[#1c1c1f] transition-colors border border-transparent hover:border-[#27272a]"
                >
                  <FileText className="w-3 h-3 text-[#71717a] shrink-0" />
                  <button
                    onClick={() => handlePreview(file.path)}
                    disabled={isBusy}
                    className="truncate flex-1 text-left hover:text-[#1E5EFF] transition-colors cursor-pointer disabled:opacity-50"
                  >
                    {fileName(file.path)}
                  </button>
                  <span className="text-[10px] text-[#71717a] shrink-0 font-mono">
                    {formatFileSize(file.size)}
                  </span>
                  {isBusy ? (
                    <Loader2 className="w-3 h-3 text-[#71717a] animate-spin shrink-0" />
                  ) : isConfirming ? (
                    <span className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => handleDelete(file.path)}
                        className="px-1.5 py-0.5 rounded bg-rose-600 hover:bg-rose-500 text-white text-[10px] font-semibold cursor-pointer"
                      >
                        删除
                      </button>
                      <button
                        onClick={() => setConfirmingPath(null)}
                        className="px-1.5 py-0.5 rounded border border-[#27272a] text-[#a1a1aa] hover:text-white text-[10px] font-semibold cursor-pointer"
                      >
                        取消
                      </button>
                    </span>
                  ) : (
                    <span className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => handlePreview(file.path)}
                        title="预览"
                        className="p-0.5 text-[#71717a] hover:text-[#1E5EFF] cursor-pointer transition-colors"
                      >
                        <Eye className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => handleDownload(file.path)}
                        title="下载"
                        className="p-0.5 text-[#71717a] hover:text-[#1E5EFF] cursor-pointer transition-colors"
                      >
                        <Download className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => setConfirmingPath(file.path)}
                        title="删除"
                        className="p-0.5 text-[#71717a] hover:text-rose-400 cursor-pointer transition-colors"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Preview modal（共享件：可缩放、Esc 关闭、嵌 FilePreview 富渲染） */}
        <FilePreviewModal
          open={!!preview}
          filename={preview ? fileName(preview.path) : ''}
          mime={preview?.mime}
          text={preview?.text}
          imageUrl={preview?.imageUrl}
          onClose={() => setPreview(null)}
          onDownload={preview && sessionId ? () => handleDownload(preview.path) : undefined}
        />
      </div>
    );
  },
);
