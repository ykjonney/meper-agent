import type { Dispatch, ReactNode, SetStateAction } from 'react';
import type { Agent } from '../../types';
import { AgentPicker } from './AgentPicker';

const SUGGESTIONS: [string, string][] = [
  ['01', '把会议记录整理成待办清单'],
  ['02', '生成一份竞品分析报告'],
  ['03', '润色这段产品文案'],
];

interface EmptySessionProps {
  composerEl: ReactNode;
  agents: Agent[];
  activeAgent: Agent | null;
  agentMenuOpen: boolean;
  setAgentMenuOpen: Dispatch<SetStateAction<boolean>>;
  onSelectAgent: (ag: Agent) => void;
  onPickSuggestion: (text: string) => void;
  modelLabel: (id?: string) => string;
}

/** 空会话欢迎界面：NEW SESSION + composer + 执行者选择 + 建议清单 */
export function EmptySession({
  composerEl, agents, activeAgent, agentMenuOpen, setAgentMenuOpen, onSelectAgent,
  onPickSuggestion, modelLabel,
}: EmptySessionProps) {
  return (
    <div className="flex-1 min-h-0 flex flex-col items-center justify-center px-10 pb-8">
      <p className="text-[10px] text-ink-faint tracking-[.22em] mb-4 font-semibold">NEW SESSION</p>
      <div className="text-[21px] font-bold text-ink mb-7" style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic' }}>
        今天想完成什么？
      </div>
      <div className="w-full max-w-[680px]">
        {composerEl}
      </div>
      {/* agent 选择：composer 下方独立行（不在输入框内） */}
      <div className="relative w-full max-w-[680px] mt-3 flex items-center gap-2">
        <AgentPicker
          agents={agents} activeAgent={activeAgent}
          open={agentMenuOpen} onToggle={() => setAgentMenuOpen(v => !v)} onClose={() => setAgentMenuOpen(false)}
          onSelect={onSelectAgent} modelLabel={modelLabel}
          menuClassName="absolute top-full mt-1.5"
          hint="切换执行者 · 会话列表随之切换"
        />
      </div>
      <div className="w-full max-w-[680px] mt-6">
        {SUGGESTIONS.map(([no, text]) => (
          <div key={no} onClick={() => onPickSuggestion(text)}
            className="flex gap-3 items-baseline text-[10.5px] text-ink-dim py-2 border-b border-line cursor-pointer hover:text-ink transition-colors text-left">
            <span className="text-brand font-bold">{no}</span>{text}
          </div>
        ))}
      </div>
    </div>
  );
}
