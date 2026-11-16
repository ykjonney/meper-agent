import { CheckCircle } from 'lucide-react';
import type { Agent } from '../../types';
import AvatarRender from '../AvatarRender';

interface AgentPickerProps {
  agents: Agent[];
  activeAgent: Agent | null;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  onSelect: (ag: Agent) => void;
  modelLabel: (id?: string) => string;
  /** 下拉菜单定位类（相对最近的定位父级，如 "absolute top-full mt-1.5 ..."） */
  menuClassName: string;
  /** trigger 右侧的提示文字（仅空会话态使用） */
  hint?: string;
}

/** 执行者（Agent）选择器：brand 圆头像 trigger + 上/下弹菜单（遮罩点击关闭）。
 *  空会话欢迎区与会话顶栏共用，仅 menuClassName 定位不同。 */
export function AgentPicker({
  agents, activeAgent, open, onToggle, onClose, onSelect, modelLabel, menuClassName, hint,
}: AgentPickerProps) {
  return (
    <>
      <span onClick={onToggle}
        className="inline-flex items-center gap-[6px] text-[10.5px] text-ink bg-panel border border-line rounded-lg px-[9px] py-[5px] cursor-pointer hover:border-line-strong transition-colors shrink-0"
        title="切换执行者">
        <span className="w-4 h-4 rounded-full bg-brand text-white flex items-center justify-center text-[8.5px]">{(activeAgent?.name ?? '?')[0]}</span>
        {activeAgent?.name ?? '选择执行者'}
        <span className="text-[8px] text-ink-faint">▾</span>
      </span>
      {hint && <span className="text-[8.5px] text-ink-faint">{hint}</span>}
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={onClose} />
          <div className={`${menuClassName} w-60 max-h-[264px] overflow-y-auto scrollbar-custom bg-panel rounded-[10px] shadow-[var(--shadow-pop)] border border-line p-1 z-50 animate-fade-in`}>
            {agents.map((ag) => {
              // 影子条目（· 草稿）与本体同 id——key/高亮按 draftPreview 区分
              const selected = activeAgent?.id === ag.id && activeAgent?.draftPreview === ag.draftPreview;
              return (
              <button key={ag.draftPreview ? `${ag.id}:draft` : ag.id} onClick={() => onSelect(ag)}
                className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left transition cursor-pointer hover:bg-panel-hover ${selected ? 'bg-brand-soft' : ''}`}>
                <span className="w-6 h-6 rounded-md bg-raise flex items-center justify-center text-[10px] shrink-0 overflow-hidden">
                  <AvatarRender value={ag.avatar} className="w-full h-full p-0.5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[11px] font-medium text-ink truncate">{ag.name}</span>
                  <span className="block text-[9.5px] text-ink-faint truncate">{modelLabel(ag.model)}</span>
                </span>
                {selected && <CheckCircle className="w-3 h-3 text-brand shrink-0" />}
              </button>
              );
            })}
          </div>
        </>
      )}
    </>
  );
}
