/**
 * ActivationWizard — 离线激活向导（未激活/失效时的全屏闸门）。
 *
 * 流程：显示本机指纹（复制/导出申请文件）→ 客户回传厂商签发的
 * license.key 内容 → 粘贴激活 → 热放行。已激活但失效（到期/指纹不符等）
 * 会显示对应错误码文案与当前授权信息。
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { KeyRound, Copy, Check, Download, Loader2, ShieldAlert, BadgeCheck } from 'lucide-react'
import {
  licenseApi,
  licenseErrorText,
  type LicenseStatus,
} from '../services/license-api'
import { getErrorMessage } from '../lib/api-client'

export function ActivationWizard({
  status,
  onActivated,
}: {
  status: LicenseStatus
  onActivated: () => void
}) {
  const [keyText, setKeyText] = useState('')
  const [copied, setCopied] = useState(false)

  const install = useMutation({
    mutationFn: (content: string) => licenseApi.install(content).then((res) => res.data),
    onSuccess: (data) => {
      if (data.activated) onActivated()
    },
  })

  const copyFingerprint = async () => {
    try {
      await navigator.clipboard.writeText(status.fingerprint)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* 剪贴板不可用时静默（可手动选中文本复制） */
    }
  }

  const downloadRequest = async () => {
    try {
      const res = await licenseApi.requestFile()
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = 'license-request.json'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      /* 下载失败不影响手动复制指纹路径 */
    }
  }

  const expired = status.code === 'LIC_E_EXPIRED'

  return (
    <div className="h-dvh flex items-center justify-center bg-[#09090b] text-[#fafafa] p-6">
      <div className="w-full max-w-xl rounded-2xl border border-[#27272a] bg-[#121214] shadow-2xl overflow-hidden">
        {/* 标题区 */}
        <div className="px-8 pt-8 pb-6 border-b border-[#27272a]">
          <div className="flex items-center gap-3">
            {status.activated ? (
              <BadgeCheck className="w-6 h-6 text-indigo-400 shrink-0" />
            ) : (
              <KeyRound className="w-6 h-6 text-amber-400 shrink-0" />
            )}
            <div>
              <h1 className="text-lg font-semibold">
                {status.activated ? '授权状态' : '系统激活'}
              </h1>
              <p className="text-xs text-[#71717a] mt-0.5">
                {status.activated ? '当前授权信息' : 'Agent Flow 需要授权后才能使用'}
              </p>
            </div>
          </div>
        </div>

        <div className="px-8 py-6 space-y-6">
          {/* 当前状态 */}
          {!status.activated && (
            <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
              <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <p className="text-sm text-amber-200/90 leading-relaxed">
                {licenseErrorText(status.code)}
              </p>
            </div>
          )}

          {/* 已有授权信息（失效续期场景可见） */}
          {status.activated && (
            <div className="rounded-lg border border-[#27272a] bg-[#18181b] px-4 py-3 space-y-1.5 text-sm">
              <InfoRow label="授权方" value={status.licensee ?? '—'} />
              <InfoRow label="版本" value={status.edition ?? '—'} />
              <InfoRow
                label="有效期至"
                value={
                  status.expires_at
                    ? `${new Date(status.expires_at).toLocaleDateString()}${
                        status.days_left != null ? `（剩 ${status.days_left} 天）` : ''
                      }`
                    : '永久授权'
                }
              />
            </div>
          )}

          {/* 步骤 1：指纹 */}
          <section>
            <StepTitle index={1} title="将本机指纹发送给供应商" />
            <div className="mt-2 flex items-center gap-2">
              <code className="flex-1 truncate rounded-md border border-[#27272a] bg-[#18181b] px-3 py-2 text-xs font-mono text-indigo-300 select-all">
                {status.fingerprint}
              </code>
              <button
                onClick={copyFingerprint}
                className="shrink-0 inline-flex items-center gap-1.5 rounded-md border border-[#27272a] bg-[#18181b] px-3 py-2 text-xs text-[#d4d4d8] hover:bg-[#232326] transition-colors cursor-pointer"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                {copied ? '已复制' : '复制'}
              </button>
              <button
                onClick={downloadRequest}
                className="shrink-0 inline-flex items-center gap-1.5 rounded-md border border-[#27272a] bg-[#18181b] px-3 py-2 text-xs text-[#d4d4d8] hover:bg-[#232326] transition-colors cursor-pointer"
              >
                <Download className="w-3.5 h-3.5" />
                申请文件
              </button>
            </div>
            <p className="mt-2 text-xs text-[#71717a]">
              {expired
                ? '续费后供应商会按此指纹重新签发，直接粘贴新授权即可。'
                : '供应商将根据此指纹签发 license.key 文件。'}
            </p>
          </section>

          {/* 步骤 2：粘贴激活 */}
          <section>
            <StepTitle index={2} title="粘贴 license.key 内容并激活" />
            <textarea
              value={keyText}
              onChange={(e) => setKeyText(e.target.value)}
              placeholder="将 license.key 文件的完整内容粘贴到这里……"
              rows={4}
              spellCheck={false}
              className="mt-2 w-full rounded-lg border border-[#27272a] bg-[#18181b] px-3 py-2.5 text-xs font-mono text-[#e4e4e7] placeholder:text-[#52525b] focus:outline-none focus:border-indigo-500/60 resize-none"
            />
            {install.isError && (
              <p className="mt-2 text-xs text-rose-400">
                {(() => {
                  const err = install.error as { code?: string } | null
                  return err?.code
                    ? licenseErrorText(err.code)
                    : getErrorMessage(install.error, '激活失败，请重试')
                })()}
              </p>
            )}
            <button
              onClick={() => keyText.trim() && install.mutate(keyText.trim())}
              disabled={!keyText.trim() || install.isPending}
              className="mt-3 w-full inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed px-4 py-2.5 text-sm font-medium text-white transition-colors cursor-pointer"
            >
              {install.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
              {install.isPending ? '正在激活…' : '激活'}
            </button>
          </section>
        </div>
      </div>
    </div>
  )
}

function StepTitle({ index, title }: { index: number; title: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="flex items-center justify-center w-5 h-5 rounded-full bg-indigo-500/15 text-indigo-400 text-[11px] font-bold">
        {index}
      </span>
      <h3 className="text-sm font-medium text-[#e4e4e7]">{title}</h3>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-[#71717a]">{label}</span>
      <span className="text-xs text-[#e4e4e7]">{value}</span>
    </div>
  )
}
