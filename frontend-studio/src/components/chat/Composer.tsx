import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { ChangeEvent, Dispatch, FormEvent, RefObject, SetStateAction } from 'react';
import {
  X, FileCode, Loader2, Paperclip, ClipboardList, CheckCircle, Mic, Brain, Check, Send, ChevronDown,
} from 'lucide-react';
import type { Agent, Message } from '../../types';
import type { Session } from '../../services/session-api';
import type { ThinkingLevel } from '../../services/agent-api';
import { agentApi, agentKeys } from '../../services/agent-api';
import { ChatVoiceComposer } from '../voice/ChatVoiceComposer';
import { Popover } from '../ui';
import { isImeComposing } from '../../lib/keyboard';
import { THINK_LEVELS, THINK_LEVEL_META, fmtContextWindow } from './message-utils';
import { useModelLabels } from './useModelLabels';
import { ModelBrandIcon } from '../ModelBrandIcon';

interface ComposerProps {
  theme: 'dark' | 'light';
  activeAgent: Agent | null;
  activeSession: Session | null;
  activeSessionId: string | null;
  // 输入状态
  inputMode: 'text' | 'voice';
  setInputMode: Dispatch<SetStateAction<'text' | 'voice'>>;
  inputText: string;
  setInputText: Dispatch<SetStateAction<string>>;
  inputTextareaRef: RefObject<HTMLTextAreaElement | null>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  pendingFiles: File[];
  setPendingFiles: Dispatch<SetStateAction<File[]>>;
  uploading: boolean;
  onUploadFile: (e: ChangeEvent<HTMLInputElement>) => void;
  // 发送 / 流式
  isStreaming: boolean;
  liveMessages: Message[];
  onSendMessage: (e?: FormEvent, overrideText?: string) => void | Promise<void>;
  onStop: () => void;
  // 偏好
  planMode: boolean;
  setPlanMode: Dispatch<SetStateAction<boolean>>;
  thinkingLevel: ThinkingLevel;
  setThinkingLevel: Dispatch<SetStateAction<ThinkingLevel>>;
  modelMenuOpen: boolean;
  setModelMenuOpen: Dispatch<SetStateAction<boolean>>;
  // 语音
  voiceAvailable: boolean;
  /** 语音按钮 tooltip：可用时"切换到语音对话"，否则说明不可用原因 */
  voiceHint: string;
  onTranscriptFinal: (text: string) => void;
  onTurnStarted: (message: { request_id?: string }) => void;
  onAgentDelta: (delta: string) => void;
  onTurnEnd: (message: { session_id?: string }) => void;
  onInterruptRequest: (text: string) => void;
  setStreamError: Dispatch<SetStateAction<string | null>>;
}

/** 聊天输入区：语音（ChatVoiceComposer）/ 文字（form）双模式，
 *  含附件上传、计划模式、模型+思考强度选择。空会话态与会话态共用。 */
export function Composer({
  theme, activeAgent, activeSession, activeSessionId,
  inputMode, setInputMode, inputText, setInputText, inputTextareaRef,
  fileInputRef, pendingFiles, setPendingFiles, uploading, onUploadFile,
  isStreaming, liveMessages, onSendMessage, onStop,
  planMode, setPlanMode, thinkingLevel, setThinkingLevel, modelMenuOpen, setModelMenuOpen,
  voiceAvailable, voiceHint, onTranscriptFinal, onTurnStarted, onAgentDelta, onTurnEnd, onInterruptRequest,
  setStreamError,
}: ComposerProps) {
  const { modelsData, modelLabel } = useModelLabels();
  const queryClient = useQueryClient();
  // 选模型回写 agent 的 default_model（下一轮即生效；也同步修正编辑页/列表里的显示）。
  const updateModelM = useMutation({
    mutationFn: ({ agentId, modelId }: { agentId: string; modelId: string }) =>
      agentApi.updateDefaultModel(agentId, modelId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.all });
    },
  });

  if (inputMode === 'voice' && voiceAvailable) {
    return (
      <ChatVoiceComposer
        agentId={activeAgent?.id}
        sessionId={activeSessionId ?? undefined}
        theme={theme}
        onExit={() => setInputMode('text')}
        onTranscriptFinal={onTranscriptFinal}
        onTurnStarted={onTurnStarted}
        onAgentDelta={onAgentDelta}
        onTurnEnd={onTurnEnd}
        onInterruptRequest={onInterruptRequest}
        onError={setStreamError}
      />
    );
  }
  return (
    <form onSubmit={onSendMessage} className="relative max-w-[840px] mx-auto bg-panel rounded-xl shadow-[var(--shadow-card)] p-3 flex flex-col justify-between">
      {pendingFiles.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {pendingFiles.map((f, i) => (
            <span key={`${f.name}-${i}`} className="flex items-center gap-1 px-2 py-0.5 rounded bg-sig-ok-soft border border-line text-[11px] text-sig-ok font-sans">
              <FileCode className="w-3 h-3" />
              <span className="max-w-[140px] truncate">{f.name}</span>
              <button
                type="button"
                onClick={() => setPendingFiles((prev) => prev.filter((_, j) => j !== i))}
                className="hover:text-ink cursor-pointer"
              >
                <X className="w-2.5 h-2.5" />
              </button>
            </span>
          ))}
        </div>
      )}
      <textarea
        ref={inputTextareaRef}
        rows={activeSession ? 2 : 4}
        value={inputText}
        onChange={(e) => setInputText(e.target.value)}
        placeholder={
          activeSession
            ? '跟我说说你的偏好和要求，我会更懂你（Enter 发送，Shift+Enter 换行）'
            : activeAgent
              ? `与 ${activeAgent.name} 开始对话（Enter 发送，Shift+Enter 换行）`
              : '请先在左侧选择或新建一个会话'
        }
        disabled={!activeAgent || isStreaming}
        className="w-full bg-transparent text-[13.5px] text-ink focus:outline-none resize-none font-sans placeholder-ink-faint leading-relaxed disabled:opacity-50"
        onKeyDown={(e) => {
          // 中文 IME 选词/确认候选的 Enter 不是发送（见 isImeComposing 注释）
          if (isImeComposing(e)) return;
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            onSendMessage();
            return;
          }
          // Esc：流式中断开生成
          if (e.key === 'Escape' && isStreaming) {
            e.preventDefault();
            onStop();
            return;
          }
          // ↑：输入框为空时快速取回上一条输入（编辑重发）
          if (e.key === 'ArrowUp' && !e.shiftKey && !inputText && activeSession) {
            const lastUser = [...liveMessages].reverse().find((m) => m.role === 'user');
            if (lastUser?.content) {
              e.preventDefault();
              setInputText(lastUser.content);
              requestAnimationFrame(() => inputTextareaRef.current?.setSelectionRange(lastUser.content.length, lastUser.content.length));
            }
          }
        }}
      />
      <div className="flex items-center justify-between gap-2 border-t border-line/50 pt-2 mt-2">
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={onUploadFile}
            disabled={!activeAgent || uploading || isStreaming}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={!activeAgent || uploading || isStreaming}
            className="w-6 h-6 rounded-md flex items-center justify-center text-ink-dim hover:bg-raise hover:text-ink transition disabled:opacity-40"
            title="上传文件附件"
          >
            {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Paperclip className="w-3.5 h-3.5" />}
          </button>
          {/* ⑤ 模式横幅：长对话中途可见的模式状态（点击退出） */}
          {planMode && (
            <div
              className="flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-brand bg-brand-soft text-[11px] text-brand cursor-pointer select-none hover:bg-brand-soft transition"
              onClick={() => setPlanMode(false)}
              title="点击退出计划模式"
            >
              <ClipboardList className="w-3 h-3" />
              计划模式进行中 — 调研设计优先，变更类操作已禁
            </div>
          )}
          {/* Plan-mode toggle（仅关闭态显示——开启态由横幅承担状态+退出，
              两者互斥防重复控件）。点击进入计划模式。 */}
          {!planMode && (
            <button
              type="button"
              onClick={() => setPlanMode(true)}
              className="flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-semibold transition cursor-pointer select-none bg-page border-line text-ink-dim hover:text-ink"
              title="计划模式（plan_mode）— 调研设计优先、不产生变更（沙盒内探索性命令保留）；路径不确定或不可逆的任务先出计划审批后再执行"
            >
              <ClipboardList className="w-3 h-3" />
              计划模式
            </button>
          )}
          <span className="hidden md:flex text-[11px] text-ink-dim font-sans items-center gap-1 select-none">
            <CheckCircle className="w-3 h-3 text-brand" />
            {isStreaming ? '正在接收流…' : uploading ? '上传中…' : '就绪'}
          </span>
        </div>
        <div className="flex items-center gap-3">
          {/* 语音按钮常显：不可用时置灰，tooltip 说明原因（隐藏按钮会让入口不可发现） */}
          <button
            type="button"
            onClick={() => setInputMode('voice')}
            disabled={!voiceAvailable || !activeAgent || isStreaming || uploading}
            className="w-7 h-7 rounded-full flex items-center justify-center text-ink-dim hover:bg-brand-soft hover:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer transition-colors duration-200"
            title={voiceHint}
            aria-label={voiceHint}
          >
            <Mic className="w-3.5 h-3.5" />
          </button>
          {/* 模型 + 思考强度选择：选模型回写 default_model；思考为会话级偏好随请求发送。
              模型行显示上下文窗口；底部思考档位直接点选（强度色区分）。 */}
          <Popover
            trigger="click"
            open={modelMenuOpen}
            onOpenChange={setModelMenuOpen}
            content={
              <div className="w-64">
                <div className="max-h-60 overflow-y-auto py-1">
                  {(modelsData?.items ?? []).length === 0 ? (
                    <div className="px-3 py-2 text-[12px] text-ink-faint">模型列表为空，请先在资源库配置</div>
                  ) : (
                    (modelsData?.items ?? []).map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        disabled={!activeAgent || updateModelM.isPending}
                        onClick={() => {
                          if (!activeAgent) return;
                          updateModelM.mutate({ agentId: activeAgent.id, modelId: m.id });
                        }}
                        className={`w-full flex items-center gap-2 px-3 py-1.5 text-left text-[12px] transition cursor-pointer disabled:opacity-50 ${
                          activeAgent?.model === m.id
                            ? 'bg-brand-soft text-brand font-semibold'
                            : 'text-ink-dim hover:bg-raise hover:text-ink'
                        }`}
                      >
                        <ModelBrandIcon name={m.name} modelId={m.model_id} providerTag={m.provider_tag} />
                        <span className="truncate">{m.name}</span>
                        <span className="ml-auto flex items-center gap-1.5 shrink-0">
                          {fmtContextWindow(m.default_params?.context_window) && (
                            <span className="text-[10px] text-ink-faint font-mono">{fmtContextWindow(m.default_params?.context_window)}</span>
                          )}
                          <span className="text-[10px] text-ink-faint font-mono">{m.compatibility_type}</span>
                        </span>
                        {activeAgent?.model === m.id && <Check className="w-3 h-3 shrink-0" />}
                      </button>
                    ))
                  )}
                </div>
                {/* 思考强度：简单档位直接点选 */}
                <div className="border-t border-line px-3 py-2 flex items-center gap-1.5">
                  <Brain className="w-3 h-3 text-ink-faint shrink-0" />
                  <span className="text-[11px] text-ink-faint shrink-0">思考</span>
                  <div className="flex gap-1 ml-auto">
                    {THINK_LEVELS.map((lv) => (
                      <button
                        key={lv}
                        type="button"
                        onClick={() => setThinkingLevel(lv)}
                        className={`px-2 py-0.5 rounded text-[11px] font-semibold transition cursor-pointer ${
                          thinkingLevel === lv
                            ? 'bg-raise'
                            : 'text-ink-faint hover:bg-raise hover:text-ink-dim'
                        }`}
                        style={thinkingLevel === lv ? { color: THINK_LEVEL_META[lv].color } : undefined}
                      >
                        {THINK_LEVEL_META[lv].label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            }
          >
            {/* Codex 式内联选择器：无框文本 + chevron，hover 轻底（对比旧带边框盒子） */}
            <button
              type="button"
              disabled={!activeAgent}
              className="hidden sm:flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-mono select-none shrink-0 transition cursor-pointer text-ink-dim hover:bg-raise hover:text-ink disabled:cursor-default disabled:opacity-60"
              title={activeAgent ? '选择模型与思考强度' : '未选择 Agent'}
            >
              <ModelBrandIcon
                name={modelLabel(activeAgent?.model)}
                modelId={modelsData?.items.find((m) => m.id === activeAgent?.model)?.model_id}
                providerTag={modelsData?.items.find((m) => m.id === activeAgent?.model)?.provider_tag}
              />
              <span>{modelLabel(activeAgent?.model)}</span>
              <ChevronDown className="w-3 h-3 text-ink-faint" />
              {activeAgent && (
                <span className="flex items-center gap-0.5 ml-1" style={{ color: thinkingLevel === 'off' ? undefined : THINK_LEVEL_META[thinkingLevel].color }}>
                  <Brain className="w-3 h-3" />
                  {thinkingLevel === 'off' ? '关' : THINK_LEVEL_META[thinkingLevel].label}
                </span>
              )}
            </button>
          </Popover>
          {isStreaming ? (
            <button
              type="button"
              onClick={onStop}
              className="w-[23px] h-[23px] rounded-full flex items-center justify-center cursor-pointer bg-sig-fail hover:opacity-90 text-white shadow-[0_2px_8px_rgba(217,58,63,.3)]"
              title="中断"
            >
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={(!inputText.trim() && pendingFiles.length === 0) || !activeAgent}
              className={`w-[23px] h-[23px] rounded-full flex items-center justify-center cursor-pointer transition ${
                (inputText.trim() || pendingFiles.length > 0) && activeAgent
                  ? 'bg-brand hover:bg-brand-hover text-white shadow-[var(--shadow-send)]'
                  : 'bg-brand opacity-40 text-white cursor-not-allowed'
              }`}
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </form>
  );
}
