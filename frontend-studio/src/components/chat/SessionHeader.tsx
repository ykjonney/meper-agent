import { PanelRight } from 'lucide-react';
import type { Dispatch, SetStateAction } from 'react';
import type { Agent } from '../../types';
import type { Session } from '../../services/session-api';
import { AgentPicker } from './AgentPicker';
import { TodoPanel } from './TodoPanel';
import type { TodoItem } from './message-utils';

interface SessionHeaderProps {
  activeSession: Session | null;
  agents: Agent[];
  activeAgent: Agent | null;
  agentMenuOpen: boolean;
  setAgentMenuOpen: Dispatch<SetStateAction<boolean>>;
  onSelectAgent: (ag: Agent) => void;
  panelOpen: boolean;
  onTogglePanel: () => void;
  modelLabel: (id?: string) => string;
  /** 当前任务清单（timeline 派生）；null/undefined = 无清单，面板不渲染。 */
  todos?: TodoItem[] | null;
}

/** 2a. 会话顶栏：执行者切换 + 衬线会话标题 + 任务清单胶囊 + 功能区开关 */
export function SessionHeader({
  activeSession, agents, activeAgent, agentMenuOpen, setAgentMenuOpen, onSelectAgent,
  panelOpen, onTogglePanel, modelLabel, todos,
}: SessionHeaderProps) {
  return (
    <div className="px-5 h-12 shrink-0 flex items-center gap-3 border-b border-line">
      <AgentPicker
        agents={agents} activeAgent={activeAgent}
        open={agentMenuOpen} onToggle={() => setAgentMenuOpen(v => !v)} onClose={() => setAgentMenuOpen(false)}
        onSelect={onSelectAgent} modelLabel={modelLabel}
        menuClassName="absolute left-5 top-12"
      />
      <span className="text-[13.5px] font-bold text-ink truncate flex-1" style={{ fontFamily: 'var(--font-serif)' }}>
        {activeSession?.title || '未命名会话'}
      </span>
      {/* 任务清单：仅最新快照（Timeline 派生），清空后不渲染 */}
      {todos && todos.length > 0 && <TodoPanel todos={todos} />}
      {/* 功能区开关：产物与后续扩展面板 */}
      <button
        onClick={onTogglePanel}
        className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition cursor-pointer ${
          panelOpen ? 'bg-brand-soft text-brand' : 'text-ink-dim hover:bg-raise hover:text-ink'
        }`}
        title={panelOpen ? '关闭功能区' : '打开功能区（产物）'}
      >
        <PanelRight className="w-4 h-4" />
      </button>
    </div>
  );
}
