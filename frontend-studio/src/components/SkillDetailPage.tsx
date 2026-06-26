/**
 * SkillDetailPage — view/edit a Skill's files.
 *
 * Directory Skills: left file tree (getFileTree) + right editor (getFileContent
 * / updateFileContent). Single-file Skills (SKILL.md only): render instructions
 * directly. Ported from frontend skill-detail-page.tsx + skill-file-tree/editor,
 * native Tailwind (no antd Tree/TextArea).
 */
import { useMemo, useState, type FC } from 'react';
import {
  ArrowLeft, Folder, FileText, Loader2, Save, Undo2, FilePen,
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  toolsApi, toolKeys, type SkillFileTreeNode,
} from '../services/tools-api';

export function SkillDetailPage({
  toolId,
  toolName,
  onBack,
}: {
  toolId: string;
  toolName: string;
  onBack: () => void;
}) {
  const { data: tool } = useQuery({
    queryKey: toolKeys.detail(toolId),
    queryFn: () => toolsApi.get(toolId),
  });

  const isDirectory = (tool?.files?.length ?? 0) > 0 || (tool?.source === 'markdown' && (tool?.files?.length ?? 0) > 0);

  return (
    <div className="space-y-4">
      {/* Breadcrumb / header */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-1.5 rounded-lg text-[#a1a1aa] hover:text-white hover:bg-[#27272a] transition cursor-pointer">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div>
          <div className="flex items-center gap-2 text-xs text-[#71717a]">
            <span>技能商店</span><span>/</span><span className="text-white font-semibold">{toolName}</span>
          </div>
          {tool && (
            <p className="text-[11px] text-[#52525b] mt-0.5">
              v{tool.version} · {tool.files?.length ?? 0} 文件 · {tool.source}
            </p>
          )}
        </div>
      </div>

      {isDirectory ? (
        <DirectoryEditor toolId={toolId} />
      ) : (
        <SingleFileView toolId={toolId} />
      )}
    </div>
  );
}

/** Directory mode: file tree + editor. */
function DirectoryEditor({ toolId }: { toolId: string }) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const { data: treeData, isLoading } = useQuery({
    queryKey: toolKeys.files(toolId),
    queryFn: () => toolsApi.getFileTree(toolId),
  });

  // Auto-select the first file once the tree loads.
  const firstFile = useMemo(() => firstLeaf(treeData?.files ?? []), [treeData]);
  if (firstFile && !selectedPath) {
    // setState in render guard — fine for one-time init.
    setTimeout(() => setSelectedPath(firstFile), 0);
  }

  return (
    <div className="flex gap-4 h-[calc(100vh-180px)] min-h-[400px]">
      {/* File tree */}
      <div className="w-72 shrink-0 rounded-xl border border-[#27272a] bg-[#18181b] overflow-y-auto p-3">
        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-[#71717a]">
            <Loader2 className="w-4 h-4 animate-spin mr-2" /> 加载文件…
          </div>
        ) : (
          <div className="space-y-0.5">
            {(treeData?.files ?? []).map((node) => (
              <TreeRow
                key={node.key}
                node={node}
                depth={0}
                selected={selectedPath}
                onSelect={setSelectedPath}
              />
            ))}
          </div>
        )}
      </div>

      {/* Editor */}
      <div className="flex-1 min-w-0">
        {selectedPath ? (
          <FileEditor toolId={toolId} filePath={selectedPath} />
        ) : (
          <div className="flex items-center justify-center h-full text-[#52525b] text-sm border border-[#27272a] rounded-xl bg-[#18181b]">
            选择左侧文件查看内容
          </div>
        )}
      </div>
    </div>
  );
}

/** Recursively render a tree node (folders expandable, files selectable). */
const TreeRow: FC<{
  node: SkillFileTreeNode;
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
          <TreeRow key={child.key} node={child} depth={depth + 1} selected={selected} onSelect={onSelect} />
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

/** Load + edit a single file, with dirty/save. */
function FileEditor({ toolId, filePath }: { toolId: string; filePath: string }) {
  const queryClient = useQueryClient();
  const [local, setLocal] = useState<string>('');
  const [loaded, setLoaded] = useState(false);

  const { data: file, isLoading } = useQuery({
    queryKey: toolKeys.fileContent(toolId, filePath),
    queryFn: () => toolsApi.getFileContent(toolId, filePath),
  });

  // Sync remote content into local once per load.
  if (!loaded && file !== undefined) {
    setTimeout(() => { setLocal(file.content); setLoaded(true); }, 0);
  }

  const isDirty = loaded && local !== (file?.content ?? '');

  const saveM = useMutation({
    mutationFn: (content: string) => toolsApi.updateFileContent(toolId, filePath, content),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: toolKeys.detail(toolId) });
      queryClient.invalidateQueries({ queryKey: toolKeys.fileContent(toolId, filePath) });
    },
  });

  return (
    <div className="h-full flex flex-col rounded-xl border border-[#27272a] bg-[#18181b] overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-[#27272a] shrink-0">
        <span className="text-[11px] font-mono text-[#a1a1aa] truncate">{filePath}</span>
        <div className="flex items-center gap-2">
          {isDirty && <span className="text-[10px] text-amber-400 font-semibold">未保存</span>}
          <button
            onClick={() => file && setLocal(file.content)}
            disabled={!isDirty}
            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] text-[#a1a1aa] hover:text-white hover:bg-[#27272a] disabled:opacity-40 transition cursor-pointer"
          >
            <Undo2 className="w-3 h-3" /> 撤销
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
      <div className="px-4 py-1.5 border-t border-[#27272a] text-[10px] text-[#52525b] shrink-0">
        {local.length} 字符
      </div>
    </div>
  );
}

/** Single-file Skill (SKILL.md): render instructions directly. */
function SingleFileView({ toolId }: { toolId: string }) {
  const { data: tool, isLoading } = useQuery({
    queryKey: toolKeys.detail(toolId),
    queryFn: () => toolsApi.get(toolId),
  });

  return (
    <div className="rounded-xl border border-[#27272a] bg-[#18181b] overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-[#27272a]">
        <FilePen className="w-4 h-4 text-indigo-400" />
        <span className="text-sm font-bold text-white">工具说明</span>
      </div>
      {isLoading ? (
        <div className="flex items-center justify-center py-12 text-[#71717a]"><Loader2 className="w-5 h-5 animate-spin mr-2" />加载…</div>
      ) : (
        <pre className="p-5 text-xs text-[#d4d4d8] font-sans whitespace-pre-wrap leading-relaxed max-h-[60vh] overflow-y-auto">
          {tool?.instructions || tool?.description || '（无说明）'}
        </pre>
      )}
    </div>
  );
}

/** Find the first leaf path in a tree (for auto-select). */
function firstLeaf(nodes: SkillFileTreeNode[]): string | null {
  for (const n of nodes) {
    if (n.is_leaf) return n.key;
    const child = firstLeaf(n.children ?? []);
    if (child) return child;
  }
  return null;
}
