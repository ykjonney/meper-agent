import { Hand, Keyboard, Mic } from 'lucide-react'
import { useVoiceConversation } from '../../hooks/voice/useVoiceConversation'
import { usePttSpaceTrigger } from '../../hooks/voice/usePttSpaceTrigger'
import { StateOrb } from './StateOrb'
import { AudioDeviceMenu } from './AudioDeviceMenu'

interface ChatVoiceComposerProps {
  agentId?: string
  sessionId?: string
  theme: 'dark' | 'light'
  onExit: () => void
  onTranscriptFinal: (text: string) => void
  onTurnStarted: (message: { request_id?: string; session_id?: string }) => void
  onAgentDelta: (text: string) => void
  onTurnEnd: (message: { request_id?: string; session_id?: string }) => void
  onInterruptRequest: (question: string) => void
  onError: (message: string) => void
}

const STATE_COPY: Record<string, string> = {
  idle: '按住麦克风或空格说话，松开自动发送',
  listening: '正在聆听，松开发送',
  thinking: 'Agent 正在思考，按住可打断',
  speaking: 'Agent 正在回复，按住可打断',
  error: '语音服务出现异常',
}

export function ChatVoiceComposer(props: ChatVoiceComposerProps) {
  const dark = props.theme === 'dark'
  const voice = useVoiceConversation({
    enabled: true,
    agentId: props.agentId,
    sessionId: props.sessionId,
    onTranscriptFinal: props.onTranscriptFinal,
    onTurnStarted: props.onTurnStarted,
    onAgentDelta: props.onAgentDelta,
    onTurnEnd: props.onTurnEnd,
    onInterruptRequest: props.onInterruptRequest,
    onError: props.onError,
  })
  const canInterrupt = voice.voiceState === 'thinking' || voice.voiceState === 'speaking'

  usePttSpaceTrigger(
    voice.connected && !!props.agentId && !!props.sessionId,
    () => void voice.press(),
    voice.release,
  )

  const exitToText = () => {
    voice.pause()
    props.onExit()
  }

  return (
    <section
      className={`relative min-h-[218px] overflow-visible rounded-xl border px-4 py-3 ${
        'border-line bg-panel'
      }`}
      aria-label="语音输入"
    >
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-sky-400/50 to-transparent" />
      <div className="relative z-10 flex items-center justify-between">
        <div className={`flex items-center gap-2 text-[11px] font-medium text-ink-dim`}>
          <span
            className={`h-2 w-2 rounded-full ${voice.connected ? 'bg-sig-ok' : 'bg-sig-wait'}`}
            aria-hidden="true"
          />
          {voice.connected ? '语音已连接' : '正在连接语音服务…'}
        </div>
        <div className="flex items-center gap-1">
          <AudioDeviceMenu
            theme={props.theme}
            inputDevices={voice.audioDevices.inputDevices}
            outputDevices={voice.audioDevices.outputDevices}
            inputDeviceId={voice.audioDevices.inputDeviceId}
            outputDeviceId={voice.audioDevices.outputDeviceId}
            onInputChange={voice.audioDevices.selectInputDevice}
            onOutputChange={voice.audioDevices.selectOutputDevice}
            loading={voice.audioDevices.loading}
            recording={voice.recording}
            outputSelectionSupported={voice.audioDevices.outputSelectionSupported}
            notice={voice.audioDevices.notice}
            error={voice.audioDeviceError}
          />
          <button
            type="button"
            onClick={exitToText}
            className="flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-[11px] font-semibold text-ink-soft hover:bg-raise transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand cursor-pointer"
            aria-label="暂停语音并切换到文字输入"
          >
            <Keyboard className="h-3.5 w-3.5" />
            文字输入
          </button>
        </div>
      </div>

      <div className="relative z-10 -mt-2 flex flex-col items-center">
        <StateOrb state={voice.voiceState} compact />
        <p className={`mt-1 min-h-5 max-w-full truncate px-4 text-center text-[11px] text-ink-dim`} aria-live="polite">
          {voice.partial ? `“${voice.partial}”` : STATE_COPY[voice.voiceState]}
        </p>

        <div className="mt-2 flex items-center gap-2">
          <button
            type="button"
            onPointerDown={(e) => {
              e.preventDefault()
              try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* ignore */ }
              void voice.press()
            }}
            onPointerUp={() => voice.release()}
            onPointerCancel={() => voice.release()}
            disabled={!voice.connected || !props.agentId || !props.sessionId}
            className={`flex min-h-11 items-center gap-2 rounded-full px-4 text-[11px] font-semibold text-white shadow-[var(--shadow-send)] transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer ${
              voice.recording
                ? 'bg-sig-fail hover:opacity-90'
                : 'bg-brand hover:bg-brand-hover'
            }`}
            aria-label={voice.recording ? '松开结束语音输入' : '按住说话'}
          >
            <Mic className="h-3.5 w-3.5" />
            {voice.recording ? '松开发送' : '按住说话'}
          </button>

          {canInterrupt && (
            <button
              type="button"
              onClick={voice.interrupt}
              className={`flex min-h-11 items-center gap-1.5 rounded-full border border-sig-wait/35 bg-sig-wait-soft px-4 text-[11px] font-semibold transition-colors duration-200 hover:bg-sig-wait-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sig-wait cursor-pointer text-sig-wait`}
              aria-label="打断 Agent 回复"
            >
              <Hand className="h-3.5 w-3.5" />
              打断
            </button>
          )}
        </div>

        {voice.error && (
          <p className={`mt-2 text-center text-[11px] text-sig-fail`} role="alert">
            {voice.error}
          </p>
        )}
      </div>
    </section>
  )
}
