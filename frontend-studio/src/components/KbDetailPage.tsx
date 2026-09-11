/**
 * KbDetailPage — llmwiki-style compiled wiki workspace (tree KB IS wiki).
 *
 *   - Left column splits into "Wiki 页面" tree + "源文件" list (extraction
 *     status per source, 3s polling while pending/processing).
 *   - Top bar: 构建 Wiki (one-click builder, running guard + status badge),
 *     检查 (lint report modal), builder-model inline select.
 *   - Right side: dual-mode page viewer (Markdown render + in-page TOC by
 *     default, textarea editor on toggle); sources open read-only
 *     extracted text.
 */
import { useEffect, useMemo, useState, type FC, type ChangeEvent, type MouseEvent as ReactMouseEvent } from 'react';
import {
  ArrowLeft, BookOpen, CheckCircle2, CircleAlert, FileText, FlaskConical,
  Folder, Loader2, Pencil, Save, Sparkles, Trash2, Undo2, Upload, X,
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  knowledgeApi, knowledgeKeys,
  type KbFileTreeNode, type KbWikiSourceItem,
} from '../services/knowledge-api';
import { modelApi } from '../services/model-api';
import { Markdown } from './Markdown';
import { confirmDialog } from './ui/confirm';
import { toast } from './ui/toast';

export function KbDetailPage({
  kbId,
  kbName,
  onBack,
}: {
  kbId: string;
  kbName: string;
  onBack: () => void;
}) {
  return (
    <div className="space-y-4">
      {/* Breadcrumb / header */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-1.5 rounded-lg text-[#a1a1aa] hover:text-white hover:bg-[#27272a] transition cursor-pointer">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs text-[#71717a]">
            <span>知识库</span><span>/</span><span className="text-white font-semibold">{kbName}</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-fuchsia-500/15 text-fuchsia-300">Wiki</span>
          </div>
          <p className="text-[11px] text-[#52525b] mt-0.5">
            上传源资料到 sources/，点「构建 Wiki」由 AI 编译成带引用的知识页面；Agent 可用 kb_guide / kb_write 维护
          </p>
        </div>
      </div>
      <WikiWorkspace kbId={kbId} />
    </div>
  );
}

/* ══════════════════════════ Wiki mode ══════════════════════════ */

function WikiWorkspace({ kbId }: { kbId: string }) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null); // "wiki/…" or "sources/…"
  const [lintOpen, setLintOpen] = useState(false);

  const { data: kb } = useQuery({
    queryKey: knowledgeKeys.detail(kbId),
    queryFn: () => knowledgeApi.get(kbId),
    refetchInterval: (q) => (q.state.data?.last_build_status === 'running' ? 3000 : false),
  });

  const { data: wikiFiles, isLoading } = useQuery({
    queryKey: knowledgeKeys.wikiFiles(kbId),
    queryFn: () => knowledgeApi.getWikiFiles(kbId),
    // 源文件提取中轮询状态；全部就绪后停。
    refetchInterval: (q) =>
      (q.state.data?.sources ?? []).some((s) => s.status === 'pending' || s.status === 'processing')
        ? 3000
        : false,
  });

  const sources = wikiFiles?.sources ?? [];
  const building = kb?.last_build_status === 'running';

  const buildM = useMutation({
    mutationFn: () => knowledgeApi.buildWiki(kbId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.detail(kbId) });
      toast.success('构建任务已派发，完成后页面自动刷新');
    },
    onError: (e: Error) => toast.error(`派发失败：${e.message}`),
  });

  const uploadM = useMutation({
    mutationFn: (files: File[]) => knowledgeApi.uploadDocuments(kbId, files),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.wikiFiles(kbId) });
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.detail(kbId) });
      if (res.errors.length) {
        toast.error(`${res.created.length} 成功 / ${res.errors.length} 失败：${res.errors[0].error}`);
      } else {
        toast.success(`已上传 ${res.created.length} 个源文件`);
      }
    },
  });

  const handleUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.currentTarget.value = '';
    if (!files.length) return;

    // 同名检测：已存在的源文件名 → 覆盖 / 自动改名 / 取消（两连问实现三选）
    const existing = new Set(
      (wikiFiles?.sources ?? []).map((s) => s.path.slice('sources/'.length)),
    );
    // 同一批内重名也算冲突（后一个会覆盖前一个）
    const seen = new Set<string>();
    const clashes = files.filter((f) => {
      if (existing.has(f.name) || seen.has(f.name)) {
        seen.add(f.name);
        return true;
      }
      seen.add(f.name);
      return false;
    });

    if (clashes.length > 0) {
      const names = clashes.map((f) => f.name).join('、');
      const overwrite = await confirmDialog({
        title: `检测到同名源文件：${names}`,
        description: '继续上传将覆盖现有文件（旧内容即刻丢失，引用它的 wiki 页不会自动更新）。是否覆盖？',
        okText: '覆盖上传',
        cancelText: '不覆盖',
        danger: true,
      });
      if (!overwrite) {
        const rename = await confirmDialog({
          title: '改为自动改名上传？',
          description: `冲突文件将改名为 report (1).pdf 形式，保留原文件。`,
          okText: '自动改名上传',
          cancelText: '取消上传',
        });
        if (!rename) return;
        uploadM.mutate(renameClashes(files, existing));
        return;
      }
    }
    uploadM.mutate(files);
  };

  return (
    <>
      <div className="flex gap-4 h-[calc(100vh-210px)] min-h-[400px]">
        {/* Left: wiki pages + sources */}
        <div className="w-72 shrink-0 rounded-xl border border-[#27272a] bg-[#18181b] overflow-y-auto p-3 space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2 px-1">
              <span className="text-[11px] text-[#71717a] font-semibold">Wiki 页面</span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setLintOpen(true)}
                  className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] text-[#a1a1aa] hover:text-white hover:bg-[#27272a] transition cursor-pointer"
                >
                  <FlaskConical className="w-3 h-3" /> 检查
                </button>
                <label className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] bg-indigo-600 hover:bg-indigo-500 text-white cursor-pointer font-semibold transition">
                  {uploadM.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
                  上传源
                  <input
                    type="file"
                    accept=".pdf,.docx,.pptx,.xlsx,.csv,.md,.markdown,.txt,.html,.htm"
                    multiple
                    className="hidden"
                    onChange={handleUpload}
                  />
                </label>
              </div>
            </div>
            {isLoading ? (
              <div className="flex items-center justify-center py-6 text-[#71717a]">
                <Loader2 className="w-4 h-4 animate-spin mr-2" /> 加载…
              </div>
            ) : (wikiFiles?.wiki ?? []).length === 0 ? (
              <p className="text-[11px] text-[#52525b] px-1 py-3 text-center">尚无页面——上传源后点「构建 Wiki」</p>
            ) : (
              <div className="space-y-0.5">
                {(wikiFiles?.wiki ?? []).map((node) => (
                  <KbTreeRow key={node.key} node={node} depth={0} selected={selected} onSelect={setSelected} />
                ))}
              </div>
            )}
          </div>

          <div className="border-t border-[#27272a] pt-3">
            <div className="flex items-center justify-between mb-2 px-1">
              <span className="text-[11px] text-[#71717a] font-semibold">源文件（只读）</span>
              <span className="text-[10px] text-[#52525b]">{sources.length}</span>
            </div>
            {sources.length === 0 ? (
              <p className="text-[11px] text-[#52525b] px-1 py-2 text-center">还没有源资料</p>
            ) : (
              <div className="space-y-0.5">
                {sources.map((s) => (
                  <WikiSourceRow key={s.path} source={s} selected={selected} onSelect={setSelected} />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right: viewer */}
        <div className="flex-1 min-w-0 flex flex-col gap-3">
          <BuildBar kbId={kbId} building={building} onBuild={() => buildM.mutate()} />
          <div className="flex-1 min-h-0">
            {selected === null ? (
              <div className="flex items-center justify-center h-full text-[#52525b] text-sm border border-[#27272a] rounded-xl bg-[#18181b]">
                选择左侧 Wiki 页面或源文件查看
              </div>
            ) : selected.startsWith('sources/') ? (
              <WikiSourceViewer kbId={kbId} path={selected} sources={sources} />
            ) : (
              // key=selected forces fresh state per file switch.
              <WikiPageViewer key={selected} kbId={kbId} filePath={selected} />
            )}
          </div>
        </div>
      </div>
      {lintOpen && <WikiLintModal kbId={kbId} onClose={() => setLintOpen(false)} onJump={setSelected} />}
    </>
  );
}

/** 构建 Wiki 按钮 + 构建模型内联选择 + 状态徽标 + 失败原因横幅。 */
function BuildBar({ kbId, building, onBuild }: { kbId: string; building: boolean; onBuild: () => void }) {
  const queryClient = useQueryClient();
  // 派发后 60s 内持续轮询——claim 置 running 前状态还是旧值，不轮询会像没反应。
  const [justDispatched, setJustDispatched] = useState(false);
  useEffect(() => {
    if (!justDispatched) return;
    const t = setTimeout(() => setJustDispatched(false), 60_000);
    return () => clearTimeout(t);
  }, [justDispatched]);

  const { data: kb } = useQuery({
    queryKey: knowledgeKeys.detail(kbId),
    queryFn: () => knowledgeApi.get(kbId),
    refetchInterval: (q) =>
      q.state.data?.last_build_status === 'running' || justDispatched ? 3000 : false,
  });
  useEffect(() => {
    // 派发后进入终态即可提前停止轮询。
    if (justDispatched && (kb?.last_build_status === 'completed' || kb?.last_build_status === 'failed')) {
      setJustDispatched(false);
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.wikiFiles(kbId) });
    }
  }, [kb?.last_build_status, justDispatched, kbId, queryClient]);

  const { data: modelsData } = useQuery({
    queryKey: ['models', 'wiki-builder'],
    queryFn: () => modelApi.list({ page_size: 100 }),
  });
  const models = (modelsData?.items ?? []).filter((m) => m.status === 'active');

  const saveModelM = useMutation({
    mutationFn: (builderModelId: string) =>
      knowledgeApi.update(kbId, { builder_model_id: builderModelId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.detail(kbId) });
      toast.success('构建模型已保存');
    },
    onError: (e: Error) => toast.error(`保存失败：${e.message}`),
  });

  const builderModelId = kb?.builder_model_id ?? '';
  const hasModel = builderModelId.startsWith('model_');
  const status = kb?.last_build_status ?? '';
  const buildError = (kb?.last_build_error ?? '').trim();
  // 已脱离 running 且派发提示仍在 → 状态已终态，清掉。
  useEffect(() => {
    if (building && status && status !== 'running') setJustDispatched(false);
  }, [building, status]);

  return (
    <div className="space-y-2 shrink-0">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <select
            value={builderModelId}
            onChange={(e) => saveModelM.mutate(e.target.value)}
            disabled={saveModelM.isPending}
            className="px-2 py-1.5 rounded-lg border border-[#27272a] bg-[#18181b] text-[11px] text-[#d4d4d8] max-w-52 cursor-pointer"
          >
            <option value="">构建模型：未选择</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
          <button
            onClick={() => {
              setJustDispatched(true);
              onBuild();
            }}
            disabled={building || !hasModel}
            title={!hasModel ? '请先选择构建模型' : building ? '构建进行中' : '消化未引用的源，更新 wiki 页面'}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition cursor-pointer"
          >
            {building ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            {building ? '构建中…' : '构建 Wiki'}
          </button>
        </div>
        {status && (
          <span
            className={`flex items-center gap-1 text-[10px] font-semibold ${
              status === 'running' ? 'text-sky-400'
              : status === 'completed' ? 'text-emerald-400'
              : status === 'failed' ? 'text-rose-400'
              : 'text-[#71717a]'
            }`}
          >
            {status === 'completed' && <CheckCircle2 className="w-3 h-3" />}
            {status === 'failed' && <CircleAlert className="w-3 h-3" />}
            上次构建：{status === 'running' ? '进行中' : status === 'completed' ? '已完成' : status === 'failed' ? '失败' : status}
            {kb?.last_build_at && status !== 'running' ? ` · ${new Date(kb.last_build_at).toLocaleString()}` : ''}
          </span>
        )}
      </div>
      {status === 'failed' && !building && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-lg border border-rose-700/40 bg-rose-950/20">
          <CircleAlert className="w-3.5 h-3.5 text-rose-400 shrink-0 mt-0.5" />
          <div className="min-w-0">
            <p className="text-[11px] text-rose-300 font-semibold">构建失败</p>
            <p className="text-[11px] text-[#d4d4d8] mt-0.5 break-words whitespace-pre-wrap">
              {buildError || '后端未返回原因——请查看 Worker 日志中的 wiki_build_failed 事件（常见：模型 API Key/地址无效、模型不支持工具调用）。'}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/** 源文件行：状态徽标 + 只读打开（点击读提取文本）。 */
function WikiSourceRow({
  source, selected, onSelect,
}: { source: KbWikiSourceItem; selected: string | null; onSelect: (p: string) => void }) {
  const isSel = selected === source.path;
  return (
    <button
      onClick={() => onSelect(source.path)}
      title={source.status === 'failed' ? source.error : source.path}
      className={`w-full flex items-center gap-1.5 py-1 px-1 text-xs rounded transition cursor-pointer ${
        isSel ? 'bg-indigo-500/10 text-indigo-300' : 'text-[#a1a1aa] hover:text-white hover:bg-[#27272a]'
      }`}
    >
      <StatusDot status={source.status} />
      <span className="truncate font-mono text-[11px]">{source.name}</span>
    </button>
  );
}

function StatusDot({ status }: { status: string }) {
  if (status === 'processing') return <Loader2 className="w-3 h-3 animate-spin text-sky-400 shrink-0" />;
  if (status === 'pending') return <CircleAlert className="w-3 h-3 text-amber-400 shrink-0" />;
  if (status === 'failed') return <CircleAlert className="w-3 h-3 text-rose-400 shrink-0" />;
  return <FileText className="w-3 h-3 text-[#52525b] shrink-0" />;
}

/** 源文件查看器：md 直读，二进制读 .extracted 提取文本（只读）。 */
function WikiSourceViewer({
  kbId, path, sources,
}: { kbId: string; path: string; sources: KbWikiSourceItem[] }) {
  const src = sources.find((s) => s.path === path);
  const isMd = ['md', 'markdown'].includes(src?.file_type ?? '');
  const readPath = isMd ? path : `sources/.extracted/${src?.name ?? ''}.md`;
  const ready = isMd || src?.status === 'ready';

  const { data: file, isLoading } = useQuery({
    queryKey: knowledgeKeys.fileContent(kbId, readPath),
    queryFn: () => knowledgeApi.getFileContent(kbId, readPath),
    enabled: ready,
  });

  if (!ready) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-2 text-sm border border-[#27272a] rounded-xl bg-[#18181b]">
        {src?.status === 'failed' ? (
          <>
            <CircleAlert className="w-6 h-6 text-rose-400" />
            <p className="text-rose-400 text-xs">提取失败：{src.error || '未知错误'}</p>
          </>
        ) : (
          <>
            <Loader2 className="w-6 h-6 animate-spin text-sky-400" />
            <p className="text-[#71717a] text-xs">文本提取中…（{src?.status}）</p>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col rounded-xl border border-[#27272a] bg-[#18181b] overflow-hidden">
      <div className="px-4 py-2 border-b border-[#27272a] shrink-0 flex items-center gap-2">
        <span className="text-[11px] font-mono text-[#a1a1aa] truncate">{path}</span>
        {!isMd && <span className="text-[10px] text-[#52525b]">提取文本（只读）</span>}
      </div>
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center text-[#71717a]"><Loader2 className="w-5 h-5 animate-spin mr-2" />加载…</div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4 text-xs font-mono text-[#d4d4d8] whitespace-pre-wrap leading-relaxed">
          {file?.content ?? '（空）'}
        </div>
      )}
    </div>
  );
}

/** Wiki 页面查看器：阅读（Markdown + 页内 TOC）/ 编辑双模式。 */
function WikiPageViewer({ kbId, filePath }: { kbId: string; filePath: string }) {
  const [editing, setEditing] = useState(false);
  const { data: file, isLoading } = useQuery({
    queryKey: knowledgeKeys.fileContent(kbId, filePath),
    queryFn: () => knowledgeApi.getFileContent(kbId, filePath),
  });

  const toc = useMemo(() => extractHeadings(file?.content ?? ''), [file?.content]);

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center text-[#71717a] border border-[#27272a] rounded-xl bg-[#18181b]">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />加载…
      </div>
    );
  }
  if (editing) {
    return <KbFileEditor kbId={kbId} filePath={filePath} onDone={() => setEditing(false)} />;
  }

  return (
    <div className="h-full flex rounded-xl border border-[#27272a] bg-[#18181b] overflow-hidden">
      {/* In-page TOC */}
      {toc.length > 0 && (
        <div className="w-44 shrink-0 border-r border-[#27272a] overflow-y-auto p-3">
          <p className="text-[10px] text-[#71717a] font-semibold mb-2">本页目录</p>
          <div className="space-y-0.5">
            {toc.map((h, i) => (
              <button
                key={`${h.text}-${i}`}
                onClick={() => scrollToHeading(h.text)}
                style={{ paddingLeft: `${(h.level - 2) * 10 + 4}px` }}
                className="w-full text-left text-[11px] text-[#a1a1aa] hover:text-white truncate py-0.5 cursor-pointer"
              >
                {h.text}
              </button>
            ))}
          </div>
        </div>
      )}
      {/* Rendered page */}
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="px-4 py-2 border-b border-[#27272a] shrink-0 flex items-center justify-between">
          <span className="text-[11px] font-mono text-[#a1a1aa] truncate">{filePath}</span>
          <button
            onClick={() => setEditing(true)}
            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] text-[#a1a1aa] hover:text-white hover:bg-[#27272a] transition cursor-pointer"
          >
            <Pencil className="w-3 h-3" /> 编辑
          </button>
        </div>
        {/* relative：让正文里的 absolute 元素（脚注 sr-only 标签等）以本容器为
            包含块，否则它们会把 #root 撑成可程序化滚动（scrollIntoView 顶起整页） */}
        <div className="relative flex-1 overflow-y-auto px-6 py-4" data-wiki-page onClick={handleAnchorClick}>
          <Markdown content={file?.content ?? ''} />
        </div>
      </div>
    </div>
  );
}

/** 提取 h2/h3 标题做页内目录。 */
function extractHeadings(md: string): { level: number; text: string }[] {
  const out: { level: number; text: string }[] = [];
  for (const line of md.split('\n')) {
    const m = /^(##)\s+(.+)$/.exec(line) || /^(###)\s+(.+)$/.exec(line);
    if (m) out.push({ level: m[1].length, text: m[2].replace(/[#*`]/g, '').trim() });
  }
  return out;
}

/** 只滚阅读容器本身定位到元素顶部。
 *  不用 scrollIntoView / 原生锚点跳转：二者都会程序化滚动 overflow:hidden
 *  的 document，每次点击把整个页面顶高一截——只滚阅读容器。 */
function scrollContainerTo(container: Element, el: Element) {
  const top =
    el.getBoundingClientRect().top -
    container.getBoundingClientRect().top +
    container.scrollTop -
    8;
  container.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
}

/** 按标题文本在渲染容器内滚动定位（页内目录用）。
 *  先精确匹配再 includes：frontmatter 会被渲染成首个 h2 且包含全部
 *  关键词，纯 includes 永远先命中它（滚回顶部，点了像没反应）。 */
function scrollToHeading(text: string) {
  const container = document.querySelector('[data-wiki-page]');
  if (!container) return;
  const headings = Array.from(container.querySelectorAll('h2, h3'));
  const target =
    headings.find((h) => (h.textContent ?? '').trim() === text) ??
    headings.find((h) => (h.textContent ?? '').includes(text));
  if (target) scrollContainerTo(container, target);
}

/** 拦截页内锚点（脚注 `[^n]` / 回链）：原生 fragment 跳转同样会
 *  程序化滚动 overflow:hidden 的 document，改为只滚阅读容器。 */
function handleAnchorClick(e: ReactMouseEvent<HTMLDivElement>) {
  const anchor = (e.target as HTMLElement).closest('a');
  const href = anchor?.getAttribute('href');
  if (!anchor || !href?.startsWith('#')) return;
  const id = decodeURIComponent(href.slice(1));
  const target = id ? document.getElementById(id) : null;
  if (!target) return;
  e.preventDefault();
  scrollContainerTo(e.currentTarget, target);
}

/** Lint 报告弹窗：问题列表，点击 wiki 页可跳转。 */
function WikiLintModal({
  kbId, onClose, onJump,
}: { kbId: string; onClose: () => void; onJump: (path: string) => void }) {
  const { data, isLoading } = useQuery({
    queryKey: knowledgeKeys.wikiLint(kbId),
    queryFn: () => knowledgeApi.lintWiki(kbId),
  });

  const sevStyle = (s: string) =>
    s === 'error' ? 'text-rose-400' : s === 'warn' ? 'text-amber-400' : 'text-sky-400';
  const sevLabel = (s: string) => (s === 'error' ? '错误' : s === 'warn' ? '警告' : '提示');

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" onClick={onClose}>
      <div
        className="w-full max-w-2xl max-h-[80vh] rounded-xl border border-[#27272a] bg-[#18181b] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-4 py-3 border-b border-[#27272a] flex items-center justify-between shrink-0">
          <div>
            <p className="text-sm font-semibold text-white">Wiki 健康检查</p>
            {data && (
              <p className="text-[11px] text-[#71717a] mt-0.5">
                页面 {data.stats.page_count} · 源 {data.stats.source_count}（已引用 {data.stats.cited_source_count}）·
                错误 {data.stats.error_count} / 警告 {data.stats.warn_count}
              </p>
            )}
          </div>
          <button onClick={onClose} className="p-1 rounded-lg text-[#a1a1aa] hover:text-white hover:bg-[#27272a] cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-1">
          {isLoading ? (
            <div className="flex items-center justify-center py-8 text-[#71717a]"><Loader2 className="w-4 h-4 animate-spin mr-2" />检查中…</div>
          ) : (data?.issues ?? []).length === 0 ? (
            <div className="flex flex-col items-center py-8 gap-2 text-emerald-400">
              <CheckCircle2 className="w-6 h-6" />
              <p className="text-xs">全部健康：脚注、引用、链接、页面覆盖无问题</p>
            </div>
          ) : (
            (data?.issues ?? []).map((i, idx) => (
              <button
                key={idx}
                onClick={() => {
                  if (i.path.startsWith('wiki/')) onJump(i.path);
                  onClose();
                }}
                className="w-full text-left px-3 py-2 rounded-lg hover:bg-[#27272a] transition cursor-pointer"
              >
                <p className="text-[11px]">
                  <span className={`font-semibold ${sevStyle(i.severity)}`}>[{sevLabel(i.severity)}]</span>{' '}
                  <span className="text-[#a1a1aa]">{i.rule}</span>{' '}
                  <span className="font-mono text-[#71717a]">{i.path}</span>
                </p>
                <p className="text-[11px] text-[#d4d4d8] mt-0.5">{i.detail}</p>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

/** Recursively render a tree node (folders expandable, files selectable). */
const KbTreeRow: FC<{
  node: KbFileTreeNode;
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
}> = ({ node, depth, selected, onSelect }) => {
  const [open, setOpen] = useState(true);
  const pad = { paddingLeft: `${depth * 12 + 8}px` };

  if (!node.is_leaf) {
    return (
      <div>
        <button
          onClick={() => setOpen((o) => !o)}
          style={pad}
          className="w-full flex items-center gap-1.5 py-1 text-xs text-[#a1a1aa] hover:text-white hover:bg-[#27272a] rounded transition cursor-pointer"
        >
          <Folder className="w-3.5 h-3.5 text-sky-400 shrink-0" />
          <span className="truncate font-medium">{node.title}</span>
        </button>
        {open && node.children?.map((child) => (
          <KbTreeRow key={child.key} node={child} depth={depth + 1} selected={selected} onSelect={onSelect} />
        ))}
      </div>
    );
  }

  const isSel = selected === node.key;
  return (
    <button
      onClick={() => onSelect(node.key)}
      style={pad}
      className={`w-full flex items-center gap-1.5 py-1 text-xs rounded transition cursor-pointer ${
        isSel ? 'bg-indigo-500/10 text-indigo-300' : 'text-[#a1a1aa] hover:text-white hover:bg-[#27272a]'
      }`}
    >
      <FileText className="w-3.5 h-3.5 text-[#71717a] shrink-0" />
      <span className="truncate font-mono">{node.title}</span>
    </button>
  );
};

/** Load + edit a single file, with dirty/save/delete. */
function KbFileEditor({
  kbId, filePath, onDone,
}: { kbId: string; filePath: string; onDone?: () => void }) {
  const queryClient = useQueryClient();
  const [local, setLocal] = useState<string>('');
  const [loaded, setLoaded] = useState(false);

  const { data: file, isLoading } = useQuery({
    queryKey: knowledgeKeys.fileContent(kbId, filePath),
    queryFn: () => knowledgeApi.getFileContent(kbId, filePath),
  });

  useEffect(() => {
    if (file !== undefined && !loaded) {
      setLocal(file.content);
      setLoaded(true);
    }
  }, [file, loaded]);

  const isDirty = loaded && local !== (file?.content ?? '');

  const saveM = useMutation({
    mutationFn: (content: string) => knowledgeApi.updateFileContent(kbId, filePath, content),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.fileContent(kbId, filePath) });
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.detail(kbId) });
    },
  });

  const deleteM = useMutation({
    mutationFn: () => knowledgeApi.deleteFile(kbId, filePath),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.files(kbId) });
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.wikiFiles(kbId) });
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.detail(kbId) });
      toast.success('文件已删除');
      onDone?.();
    },
  });

  const handleDelete = async () => {
    const ok = await confirmDialog({
      title: `删除文件「${filePath}」？`,
      okText: '删除',
      danger: true,
    });
    if (ok) deleteM.mutate();
  };

  return (
    <div className="h-full flex flex-col rounded-xl border border-[#27272a] bg-[#18181b] overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-[#27272a] shrink-0">
        <span className="text-[11px] font-mono text-[#a1a1aa] truncate">{filePath}</span>
        <div className="flex items-center gap-2">
          {isDirty && <span className="text-[10px] text-amber-400 font-semibold">未保存</span>}
          {onDone && (
            <button
              onClick={onDone}
              className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] text-[#a1a1aa] hover:text-white hover:bg-[#27272a] transition cursor-pointer"
            >
              <BookOpen className="w-3 h-3" /> 阅读
            </button>
          )}
          <button
            onClick={() => file && setLocal(file.content)}
            disabled={!isDirty}
            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] text-[#a1a1aa] hover:text-white hover:bg-[#27272a] disabled:opacity-40 transition cursor-pointer"
          >
            <Undo2 className="w-3 h-3" /> 撤销
          </button>
          <button
            onClick={handleDelete}
            disabled={deleteM.isPending}
            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] text-rose-400 hover:bg-rose-950/30 disabled:opacity-40 transition cursor-pointer"
          >
            {deleteM.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
            删除
          </button>
          <button
            onClick={() => saveM.mutate(local)}
            disabled={!isDirty || saveM.isPending}
            className="flex items-center gap-1 px-3 py-1 rounded-lg text-[11px] bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 transition cursor-pointer font-semibold"
          >
            {saveM.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
            保存
          </button>
        </div>
      </div>

      {/* Editor area */}
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center text-[#71717a]"><Loader2 className="w-5 h-5 animate-spin mr-2" />加载…</div>
      ) : (
        <textarea
          value={local}
          onChange={(e) => setLocal(e.target.value)}
          className="flex-1 w-full p-4 bg-transparent text-[#fafafa] font-mono text-xs leading-relaxed resize-none focus:outline-none"
          spellCheck={false}
        />
      )}
      <div className="px-4 py-1.5 border-t border-[#27272a] text-[10px] text-[#52525b] shrink-0">{local.length} 字符</div>
    </div>
  );
}

/** Find the first leaf path in a tree (for auto-select). */
function firstLeaf(nodes: KbFileTreeNode[]): string | null {
  for (const n of nodes) {
    if (n.is_leaf) return n.key;
    const child = firstLeaf(n.children ?? []);
    if (child) return child;
  }
  return null;
}

/** Rename files that clash with existing (or in-batch) names to `stem (n).ext`. */
function renameClashes(files: File[], existing: Set<string>): File[] {
  const used = new Set(existing);
  return files.map((f) => {
    if (!used.has(f.name)) {
      used.add(f.name);
      return f;
    }
    const dot = f.name.lastIndexOf('.');
    const stem = dot > 0 ? f.name.slice(0, dot) : f.name;
    const ext = dot > 0 ? f.name.slice(dot) : '';
    for (let i = 1; ; i++) {
      const candidate = `${stem} (${i})${ext}`;
      if (!used.has(candidate)) {
        used.add(candidate);
        return new File([f], candidate, { type: f.type, lastModified: f.lastModified });
      }
    }
  });
}
