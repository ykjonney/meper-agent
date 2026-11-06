/**
 * VoiceConfigPage — admin page for voice ASR/TTS config (DB singleton).
 *
 * Providers keep independent credentials and settings. Switching the active
 * provider only changes which saved provider is used by the unified voice path.
 *
 * 形态：纸墨×靛蓝设置分区（Kicker + panel 卡 + 行式配置/下划线输入 +
 * 供应商类型卡），与外部接入 / 全局参数 Tab 同语言。
 */
import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Flame, Sparkles, Cloud } from 'lucide-react'
import {
  voiceConfigApi,
  voiceConfigKeys,
  type VoiceProvider,
} from '../../services/voice-config-api'
import { VoicePicker } from './VoicePicker'
import { getErrorMessage } from '../../lib/api-client'
import { Kicker } from '../SystemSettings'

const ZHIPU_VOICES = [
  { id: 'tongtong', name: '彤彤' },
  { id: 'chuichui', name: '锤锤' },
  { id: 'xiaochen', name: '小陈' },
  { id: 'jam', name: 'jam' },
  { id: 'kazi', name: 'kazi' },
  { id: 'douji', name: 'douji' },
  { id: 'luodo', name: 'luodo' },
]

const ALIYUN_VOICES = [
  { id: 'Cherry', name: 'Cherry' },
  { id: 'Serena', name: 'Serena' },
  { id: 'Ethan', name: 'Ethan' },
  { id: 'Chelsie', name: 'Chelsie' },
  { id: 'Dylan', name: 'Dylan' },
]

const PROVIDERS: Array<{ id: VoiceProvider; label: string; detail: string }> = [
  { id: 'volcano', label: '火山 Agent Plan', detail: '保持现有 ASR/TTS 接入方式' },
  { id: 'zhipu', label: '智谱 GLM', detail: 'GLM-ASR-2512 + GLM-TTS' },
  { id: 'aliyun', label: '阿里百炼', detail: 'Qwen ASR + Qwen TTS' },
]

const PROVIDER_ICONS: Record<VoiceProvider, typeof Flame> = {
  volcano: Flame,
  zhipu: Sparkles,
  aliyun: Cloud,
}

export function VoiceConfigPage({ theme }: { theme: 'dark' | 'light' }) {
  const qc = useQueryClient()
  const { data: cfg, isLoading } = useQuery({
    queryKey: voiceConfigKeys.detail,
    queryFn: voiceConfigApi.get,
  })

  const [activeProvider, setActiveProvider] = useState<VoiceProvider>('volcano')
  const [ttsEnabled, setTtsEnabled] = useState(true)
  const [apiKey, setApiKey] = useState('')
  const [ttsVoice, setTtsVoice] = useState('zh_female_vv_uranus_bigtts')

  const [zhipuApiKey, setZhipuApiKey] = useState('')
  const [zhipuAsrModel, setZhipuAsrModel] = useState('glm-asr-2512')
  const [zhipuAsrUrl, setZhipuAsrUrl] = useState('https://open.bigmodel.cn/api/paas/v4/audio/transcriptions')
  const [zhipuTtsModel, setZhipuTtsModel] = useState('glm-tts')
  const [zhipuTtsUrl, setZhipuTtsUrl] = useState('https://open.bigmodel.cn/api/paas/v4/audio/speech')
  const [zhipuVoice, setZhipuVoice] = useState('tongtong')
  const [zhipuSpeed, setZhipuSpeed] = useState(1)
  const [zhipuVolume, setZhipuVolume] = useState(1)

  const [aliyunApiKey, setAliyunApiKey] = useState('')
  const [aliyunAsrModel, setAliyunAsrModel] = useState('qwen3-asr-flash')
  const [aliyunAsrUrl, setAliyunAsrUrl] = useState('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions')
  const [aliyunTtsModel, setAliyunTtsModel] = useState('qwen3-tts-flash')
  const [aliyunTtsUrl, setAliyunTtsUrl] = useState('https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation')
  const [aliyunVoice, setAliyunVoice] = useState('Cherry')
  const [aliyunLanguage, setAliyunLanguage] = useState('Chinese')

  const [inputRate, setInputRate] = useState(16000)
  const [outputRate, setOutputRate] = useState(24000)
  const [vadMode, setVadMode] = useState('energy')
  const [vadThreshold, setVadThreshold] = useState(0.12)
  const [vadSilence, setVadSilence] = useState(600)
  const [status, setStatus] = useState<{ type: 'success' | 'error' | 'info'; msg: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [previewText, setPreviewText] = useState('你好，我是你的智能语音助手，很高兴和你对话。')
  const [preview, setPreview] = useState<{ voiceType: string; phase: 'loading' | 'playing' } | null>(null)
  const [previewError, setPreviewError] = useState('')
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const audioUrlRef = useRef('')
  const previewRequestRef = useRef(0)

  useEffect(() => {
    if (!cfg) return
    setActiveProvider(cfg.active_provider ?? 'volcano')
    setTtsEnabled(cfg.tts_enabled ?? true)
    setTtsVoice(cfg.tts.voice_type)
    setZhipuAsrModel(cfg.zhipu.asr_model)
    setZhipuAsrUrl(cfg.zhipu.asr_url)
    setZhipuTtsModel(cfg.zhipu.tts_model)
    setZhipuTtsUrl(cfg.zhipu.tts_url)
    setZhipuVoice(cfg.zhipu.voice_type)
    setZhipuSpeed(cfg.zhipu.speed)
    setZhipuVolume(cfg.zhipu.volume)
    setAliyunAsrModel(cfg.aliyun.asr_model)
    setAliyunAsrUrl(cfg.aliyun.asr_url)
    setAliyunTtsModel(cfg.aliyun.tts_model)
    setAliyunTtsUrl(cfg.aliyun.tts_url)
    setAliyunVoice(cfg.aliyun.voice_type)
    setAliyunLanguage(cfg.aliyun.language_type)
    setInputRate(cfg.audio.input_rate)
    setOutputRate(cfg.audio.output_rate)
    setVadMode(cfg.vad.mode)
    setVadThreshold(cfg.vad.threshold)
    setVadSilence(cfg.vad.silence_ms)
  }, [cfg])

  const stopPreview = () => {
    previewRequestRef.current += 1
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current)
      audioUrlRef.current = ''
    }
    setPreview(null)
  }

  useEffect(() => () => {
    audioRef.current?.pause()
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current)
  }, [])

  const playPreview = async (voiceType: string) => {
    if (!voiceType.trim() || !previewText.trim()) return
    if (preview?.voiceType === voiceType) {
      if (preview.phase === 'playing') stopPreview()
      return
    }

    stopPreview()
    const requestId = previewRequestRef.current
    setPreviewError('')
    setPreview({ voiceType, phase: 'loading' })
    try {
      const audioBlob = await voiceConfigApi.preview(voiceType, previewText.trim())
      if (requestId !== previewRequestRef.current) return
      const objectUrl = URL.createObjectURL(audioBlob)
      const audio = new Audio(objectUrl)
      audioRef.current = audio
      audioUrlRef.current = objectUrl
      audio.onended = stopPreview
      audio.onerror = () => {
        stopPreview()
        setPreviewError('试听音频播放失败')
      }
      await audio.play()
      if (requestId !== previewRequestRef.current) return
      setPreview({ voiceType, phase: 'playing' })
    } catch (error) {
      if (requestId !== previewRequestRef.current) return
      stopPreview()
      setPreviewError(getErrorMessage(error, '操作失败'))
    }
  }

  const save = async () => {
    setSaving(true)
    setStatus(null)
    try {
      const saved = await voiceConfigApi.save({
        active_provider: activeProvider,
        tts_enabled: ttsEnabled,
        api_key: apiKey || null,
        asr: {},
        tts: { voice_type: ttsVoice },
        zhipu: {
          api_key: zhipuApiKey || null,
          asr_model: zhipuAsrModel,
          asr_url: zhipuAsrUrl,
          tts_model: zhipuTtsModel,
          tts_url: zhipuTtsUrl,
          voice_type: zhipuVoice,
          speed: zhipuSpeed,
          volume: zhipuVolume,
        },
        aliyun: {
          api_key: aliyunApiKey || null,
          asr_model: aliyunAsrModel,
          asr_url: aliyunAsrUrl,
          tts_model: aliyunTtsModel,
          tts_url: aliyunTtsUrl,
          voice_type: aliyunVoice,
          language_type: aliyunLanguage,
        },
        audio: { input_rate: inputRate, output_rate: outputRate },
        vad: { mode: vadMode, threshold: vadThreshold, silence_ms: vadSilence },
      })
      setApiKey('')
      setZhipuApiKey('')
      setAliyunApiKey('')
      qc.setQueryData(voiceConfigKeys.detail, saved)
      qc.invalidateQueries({ queryKey: voiceConfigKeys.detail })
      qc.invalidateQueries({ queryKey: voiceConfigKeys.status })
      setStatus({ type: 'success', msg: '已保存；新建或重新连接语音会话后生效。' })
    } catch (e) {
      setStatus({ type: 'error', msg: getErrorMessage(e, '操作失败') })
    } finally {
      setSaving(false)
    }
  }

  const test = async () => {
    if (cfg?.active_provider !== activeProvider) {
      setStatus({ type: 'info', msg: '切换供应商后请先保存配置，再测试连通。' })
      return
    }
    if (cfg?.tts_enabled !== ttsEnabled) {
      setStatus({ type: 'info', msg: '修改语音播报开关后请先保存，再测试连通。' })
      return
    }
    setStatus({ type: 'info', msg: '测试中…' })
    try {
      const r = await voiceConfigApi.test()
      setStatus({ type: r.success ? 'success' : 'error', msg: r.message })
    } catch (e) {
      setStatus({ type: 'error', msg: getErrorMessage(e, '操作失败') })
    }
  }

  const onProviderChange = (provider: VoiceProvider) => {
    stopPreview()
    setPreviewError('')
    setActiveProvider(provider)
  }

  const previewVoice = activeProvider === 'zhipu' ? zhipuVoice : activeProvider === 'aliyun' ? aliyunVoice : ttsVoice
  const providerSaved = cfg?.active_provider === activeProvider
  const keyConfigured = activeProvider === 'zhipu'
    ? !!cfg?.zhipu.api_key_masked
    : activeProvider === 'aliyun'
      ? !!cfg?.aliyun.api_key_masked
      : !!cfg?.api_key_masked
  const previewDisabled = !providerSaved || !keyConfigured || !previewText.trim()

  /* ── 行式配置件（label 左 + 控件右，行间 hairline）────────────── */

  const panel = 'bg-panel border border-line rounded-xl shadow-[var(--shadow-card)] px-4 py-1'

  const FieldRow = ({ label, value, onChange, placeholder, type = 'text' }: {
    label: string; value: string | number; onChange: (v: string) => void; placeholder?: string; type?: string
  }) => (
    <label className="flex items-center gap-3 py-2.5 border-b border-line last:border-0">
      <span className="text-xs text-ink-dim shrink-0 w-32">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 min-w-0 border-0 border-b border-transparent bg-transparent px-0 py-0.5 text-[13px] text-ink placeholder:text-ink-faint focus:outline-none focus:border-brand transition"
      />
    </label>
  )

  const FixedRow = ({ label, value }: { label: string; value: string }) => (
    <div className="flex items-center gap-3 py-2.5 border-b border-line last:border-0">
      <span className="text-xs text-ink-dim shrink-0 w-32">{label}</span>
      <code className="flex-1 min-w-0 text-xs text-ink-soft font-mono truncate" title={value}>{value}</code>
    </div>
  )

  const SelectRow = ({ label, value, onChange, children }: {
    label: string; value: string; onChange: (v: string) => void; children: React.ReactNode
  }) => (
    <label className="flex items-center gap-3 py-2.5 border-b border-line last:border-0">
      <span className="text-xs text-ink-dim shrink-0 w-32">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 min-w-0 border-0 border-b border-transparent bg-transparent px-0 py-0.5 text-[13px] text-ink focus:outline-none focus:border-brand transition cursor-pointer"
      >
        {children}
      </select>
    </label>
  )

  /** 网格参数字段（窄格上下排列：label 上 + 下划线输入下） */
  const GridField = ({ label, value, onChange, type = 'text' }: {
    label: string; value: string | number; onChange: (v: string) => void; type?: string
  }) => (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] text-ink-dim">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border-0 border-b border-line-strong bg-transparent px-0 py-1 text-[13px] text-ink focus:outline-none focus:border-brand transition"
      />
    </label>
  )

  if (isLoading) return <div className="text-sm text-ink-dim">加载语音配置…</div>

  return (
    <div className="space-y-5 max-w-3xl text-ink">
      {/* 说明 + 上次测试徽标 */}
      <div className="flex items-center justify-between gap-4">
        <p className="text-xs text-ink-dim">
          选择语音供应商后配置对应 API Key。凭证加密存储，切换后保存生效。
        </p>
        {cfg?.last_test_at && (
          <span className={`text-xs shrink-0 font-medium ${cfg.last_test_success ? 'text-sig-ok' : 'text-sig-fail'}`}>
            上次测试：{cfg.last_test_success ? '通过' : '失败'}
          </span>
        )}
      </div>

      {/* 语音播报开关行 */}
      <div className={panel}>
        <button
          type="button"
          role="switch"
          aria-checked={ttsEnabled}
          onClick={() => setTtsEnabled((enabled) => !enabled)}
          className="flex w-full items-center justify-between gap-4 py-3 text-left focus-visible:outline-none cursor-pointer"
        >
          <span className="min-w-0">
            <span className="block text-[13px] font-semibold text-ink">语音播报</span>
            <span className="mt-0.5 block text-[11px] leading-relaxed text-ink-dim">
              关闭后语音对话仅做语音识别，智能体回复以文字显示，不再合成播报。
            </span>
          </span>
          <span
            className={`relative h-6 w-11 shrink-0 rounded-full transition-colors duration-200 flex items-center p-0.5 ${
              ttsEnabled ? 'bg-brand' : 'bg-raise'
            }`}
            aria-hidden="true"
          >
            <span
              className={`w-5 h-5 rounded-full bg-white shadow-sm block transition-transform duration-200 ${
                ttsEnabled ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </span>
        </button>
      </div>

      {/* 供应商类型卡（单选，参照 resource-create-edit 类型卡形态） */}
      <div>
        <Kicker hint="切换后需保存生效">PROVIDER · 语音供应商</Kicker>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          {PROVIDERS.map((p) => {
            const on = activeProvider === p.id
            const Icon = PROVIDER_ICONS[p.id]
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => onProviderChange(p.id)}
                className={`text-left rounded-xl border-[1.5px] px-3.5 py-3 transition cursor-pointer ${
                  on ? 'border-brand bg-brand-soft' : 'border-line bg-panel hover:border-line-strong'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`w-[22px] h-[22px] rounded-[7px] flex items-center justify-center shrink-0 ${
                    on ? 'bg-brand-soft text-brand' : 'bg-raise text-ink-dim'
                  }`}>
                    <Icon size={12} />
                  </span>
                  <span className={`text-[13px] font-bold ${on ? 'text-brand' : 'text-ink'}`}>{p.label}</span>
                </div>
                <div className="flex items-center gap-1.5 mt-1.5">
                  <span className="text-[11px] text-ink-faint leading-relaxed">{p.detail}</span>
                </div>
                {cfg?.active_provider === p.id && (
                  <span className="af-pill af-pill-ok mt-2">使用中</span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {activeProvider === 'volcano' && (
        <>
          <div>
            <Kicker>CREDENTIAL · Agent Plan 凭证</Kicker>
            <div className={panel}>
              <FieldRow
                label="专属 API Key"
                value={apiKey}
                onChange={setApiKey}
                placeholder={cfg?.api_key_masked ? `已配置：${cfg.api_key_masked}（留空不改）` : 'Agent Plan 专属 API Key'}
                type="password"
              />
            </div>
            <p className="text-[11px] text-ink-faint mt-2">
              无需 App ID 或 Access Token；ASR 与 TTS 共用一个专属 API Key ·{' '}
              <a href="https://console.volcengine.com/ark/region:cn-beijing/openManagement?LLM=%7B%7D&OpenModelVisible=false&advancedActiveKey=agentPlan" target="_blank" rel="noreferrer" className="text-brand hover:opacity-75">前往火山方舟获取</a>
            </p>
          </div>

          <div>
            <Kicker>ASR · 语音识别（平台托管）</Kicker>
            <div className={panel}>
              <FixedRow label="Resource-Id" value={cfg?.asr.resource_id ?? 'volc.seedasr.sauc.duration'} />
              <FixedRow label="WebSocket URL" value={cfg?.asr.url ?? 'wss://openspeech.bytedance.com/api/v3/plan/sauc/bigmodel_async'} />
            </div>
          </div>

          <div>
            <Kicker>TTS · 语音合成（平台托管）</Kicker>
            <div className={panel}>
              <FixedRow label="Resource-Id" value={cfg?.tts.resource_id ?? 'seed-tts-2.0'} />
              <FixedRow label="WebSocket URL" value={cfg?.tts.url ?? 'wss://openspeech.bytedance.com/api/v3/plan/tts/bidirection'} />
            </div>
          </div>
        </>
      )}

      {activeProvider === 'zhipu' && (
        <>
          <div>
            <Kicker>CREDENTIAL · 智谱凭证</Kicker>
            <div className={panel}>
              <FieldRow
                label="智谱 API Key"
                value={zhipuApiKey}
                onChange={setZhipuApiKey}
                placeholder={cfg?.zhipu.api_key_masked ? `已配置：${cfg.zhipu.api_key_masked}（留空不改）` : '智谱 API Key'}
                type="password"
              />
            </div>
            <p className="text-[11px] text-ink-faint mt-2">
              ASR 与 TTS 共用智谱开放平台 API Key ·{' '}
              <a href="https://bigmodel.cn/console/modelcenter/square" target="_blank" rel="noreferrer" className="text-brand hover:opacity-75">前往智谱模型广场</a>
            </p>
          </div>

          <div>
            <Kicker>ASR · 语音识别</Kicker>
            <div className={panel}>
              <FieldRow label="模型" value={zhipuAsrModel} onChange={setZhipuAsrModel} />
              <FieldRow label="HTTP URL" value={zhipuAsrUrl} onChange={setZhipuAsrUrl} />
            </div>
            <p className="text-[11px] text-ink-faint mt-2">智谱 ASR 第一版在松开说话后提交本段录音识别。</p>
          </div>

          <div>
            <Kicker>TTS · 语音合成</Kicker>
            <div className={panel}>
              <FieldRow label="模型" value={zhipuTtsModel} onChange={setZhipuTtsModel} />
              <FieldRow label="HTTP URL" value={zhipuTtsUrl} onChange={setZhipuTtsUrl} />
              <SelectRow label="系统音色" value={zhipuVoice} onChange={setZhipuVoice}>
                {ZHIPU_VOICES.map((voice) => <option key={voice.id} value={voice.id}>{voice.name}（{voice.id}）</option>)}
              </SelectRow>
              <FieldRow label="自定义/当前 voice" value={zhipuVoice} onChange={setZhipuVoice} />
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 mt-3">
              <GridField label="语速" value={zhipuSpeed} onChange={(v) => setZhipuSpeed(Number(v) || 1)} type="number" />
              <GridField label="音量" value={zhipuVolume} onChange={(v) => setZhipuVolume(Number(v) || 1)} type="number" />
            </div>
          </div>
        </>
      )}

      {activeProvider === 'aliyun' && (
        <>
          <div>
            <Kicker>CREDENTIAL · 阿里百炼凭证</Kicker>
            <div className={panel}>
              <FieldRow
                label="百炼 API Key"
                value={aliyunApiKey}
                onChange={setAliyunApiKey}
                placeholder={cfg?.aliyun.api_key_masked ? `已配置：${cfg.aliyun.api_key_masked}（留空不改）` : '阿里百炼 API Key'}
                type="password"
              />
            </div>
            <p className="text-[11px] text-ink-faint mt-2">
              ASR 与 TTS 共用百炼 API Key，北京地域模型请使用北京地域 API Key ·{' '}
              <a href="https://bailian.console.aliyun.com/cn-beijing?tab=model#/model-market" target="_blank" rel="noreferrer" className="text-brand hover:opacity-75">前往阿里百炼模型广场</a>
            </p>
          </div>

          <div>
            <Kicker>ASR · 语音识别</Kicker>
            <div className={panel}>
              <FieldRow label="模型" value={aliyunAsrModel} onChange={setAliyunAsrModel} />
              <FieldRow label="HTTP URL" value={aliyunAsrUrl} onChange={setAliyunAsrUrl} />
            </div>
            <p className="text-[11px] text-ink-faint mt-2">阿里百炼 ASR 第一版在松开说话后提交本段录音识别。</p>
          </div>

          <div>
            <Kicker>TTS · 语音合成</Kicker>
            <div className={panel}>
              <FieldRow label="模型" value={aliyunTtsModel} onChange={setAliyunTtsModel} />
              <FieldRow label="HTTP URL" value={aliyunTtsUrl} onChange={setAliyunTtsUrl} />
              <SelectRow label="系统音色" value={aliyunVoice} onChange={setAliyunVoice}>
                {ALIYUN_VOICES.map((voice) => <option key={voice.id} value={voice.id}>{voice.name}</option>)}
              </SelectRow>
              <FieldRow label="自定义/当前 voice" value={aliyunVoice} onChange={setAliyunVoice} />
              <SelectRow label="语言" value={aliyunLanguage} onChange={setAliyunLanguage}>
                <option value="Chinese">Chinese</option>
                <option value="English">English</option>
                <option value="Auto">Auto</option>
              </SelectRow>
            </div>
          </div>
        </>
      )}

      {/* 试听 */}
      <div>
        <Kicker>PREVIEW · 试听</Kicker>
        <div className="bg-panel border border-line rounded-xl shadow-[var(--shadow-card)] px-4 py-3 space-y-3">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-ink-dim flex items-center justify-between">
              试听文本
              <span className="text-ink-faint font-mono">{previewText.length}/120</span>
            </span>
            <input
              value={previewText}
              onChange={(event) => setPreviewText(event.target.value.slice(0, 120))}
              placeholder="输入一小段用于试听的文字"
              className="w-full border-0 border-b border-line-strong bg-transparent px-0 py-1 text-[13px] text-ink placeholder:text-ink-faint focus:outline-none focus:border-brand transition"
            />
          </label>
          {activeProvider === 'volcano' ? (
            <VoicePicker
              value={ttsVoice}
              onChange={(voiceType) => {
                stopPreview()
                setPreviewError('')
                setTtsVoice(voiceType)
              }}
              theme={theme}
              preview={preview}
              previewDisabled={previewDisabled}
              onPreview={playPreview}
            />
          ) : (
            <div className="flex items-center gap-3">
              <button
                onClick={() => playPreview(previewVoice)}
                disabled={previewDisabled}
                className="af-btn af-btn-secondary"
              >
                {preview?.voiceType === previewVoice && preview.phase === 'playing' ? '停止试听' : '试听音色'}
              </button>
              <span className="text-xs text-ink-dim">当前：{previewVoice}</span>
            </div>
          )}
          {previewDisabled && <p className="text-[11px] text-sig-wait">保存当前供应商的 API Key 后即可试听音色。</p>}
          {previewError && <p className="text-[11px] text-sig-fail">{previewError}</p>}
        </div>
      </div>

      {/* 音频参数 */}
      <div>
        <Kicker hint="采样率与断句检测">AUDIO · 音频参数</Kicker>
        <div className="bg-panel border border-line rounded-xl shadow-[var(--shadow-card)] px-4 py-3 grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-3">
          <GridField label="上行采样率" value={inputRate} onChange={(v) => setInputRate(Number(v) || 16000)} type="number" />
          <GridField label="下行采样率" value={outputRate} onChange={(v) => setOutputRate(Number(v) || 24000)} type="number" />
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-ink-dim">VAD 模式</span>
            <select
              value={vadMode}
              onChange={(e) => setVadMode(e.target.value)}
              className="w-full border-0 border-b border-line-strong bg-transparent px-0 py-1 text-[13px] text-ink focus:outline-none focus:border-brand transition cursor-pointer"
            >
              <option value="energy">energy（无依赖）</option>
              <option value="silero">silero（更准，需装库）</option>
              <option value="off">off（仅 ASR 端点）</option>
            </select>
          </label>
          <GridField label="VAD 阈值" value={vadThreshold} onChange={(v) => setVadThreshold(Number(v) || 0.12)} type="number" />
          <GridField label="静音时长(ms)" value={vadSilence} onChange={(v) => setVadSilence(Number(v) || 600)} type="number" />
        </div>
      </div>

      {/* 操作行 */}
      <div className="flex items-center gap-3 pt-1">
        <button onClick={save} disabled={saving} className="af-btn af-btn-primary">
          {saving ? '保存中…' : '保存配置'}
        </button>
        <button onClick={test} className="af-btn af-btn-secondary">测试连通</button>
        {status && (
          <span className={`text-xs ${status.type === 'success' ? 'text-sig-ok' : status.type === 'error' ? 'text-sig-fail' : 'text-sig-wait'}`}>
            {status.msg}
          </span>
        )}
      </div>
      <p className="text-[11px] text-ink-faint">切换供应商后需保存配置；已保存的其他供应商凭证会保留，方便随时切回。</p>
    </div>
  )
}
