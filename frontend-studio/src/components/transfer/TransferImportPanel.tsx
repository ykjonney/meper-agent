/**
 * TransferImportPanel — afpkg 导入面板（导入导出中心的「导入」Tab 内嵌版）。
 *
 * 流程：选 zip → 用当前选项跑 dry_run 预检 → 展示报告（新建/复用/跳过/
 * 警告/错误）→ 确认导入 → onImported 回调（刷新列表）。
 * 由 TransferImportDialog 演化而来（去弹窗外壳，成为页面 Tab 内容）。
 */
import { useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, FileArchive, Loader2, Upload, XCircle } from 'lucide-react'
import {
  importPackage,
  TRANSFER_KIND_LABELS,
  type ImportReport,
} from '../../services/transfer-api'
import { toast } from '../ui/toast'

type Phase = 'select' | 'previewing' | 'report' | 'importing' | 'done'

export function TransferImportPanel({ onImported }: { onImported: () => void }) {
  const [phase, setPhase] = useState<Phase>('select')
  const [file, setFile] = useState<File | null>(null)
  const [reuseExisting, setReuseExisting] = useState(true)
  const [conflict, setConflict] = useState<'rename' | 'skip'>('rename')
  const [report, setReport] = useState<ImportReport | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const runPreview = (f: File) => {
    setFile(f)
    setPhase('previewing')
    setReport(null)
    importPackage(f, { dryRun: true, reuseExisting, conflict })
      .then((r) => {
        setReport(r)
        setPhase('report')
      })
      .catch((e: Error) => {
        toast.error(e.message)
        setPhase('select')
      })
  }

  const runImport = () => {
    if (!file) return
    setPhase('importing')
    importPackage(file, { dryRun: false, reuseExisting, conflict })
      .then((r) => {
        setReport(r)
        setPhase('done')
        toast.success(
          `导入完成：新建 ${r.summary.created}，复用 ${r.summary.reused}` +
            (r.summary.errors ? `，失败 ${r.summary.errors}` : ''),
        )
        onImported()
      })
      .catch((e: Error) => {
        toast.error(e.message)
        setPhase('report')
      })
  }

  const busy = phase === 'previewing' || phase === 'importing'
  const kindLabel = (k: string) => TRANSFER_KIND_LABELS[k] ?? k

  return (
    <div className="space-y-4">
      {/* 文件选择 */}
      <div
        onClick={() => !busy && phase !== 'done' && inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-8 text-center transition ${
          busy || phase === 'done'
            ? 'border-line cursor-default'
            : 'border-line-strong hover:border-brand cursor-pointer'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".zip"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) runPreview(f)
            e.target.value = ''
          }}
        />
        {phase === 'previewing' ? (
          <div className="flex items-center justify-center gap-2 text-ink-dim text-sm">
            <Loader2 className="w-4 h-4 animate-spin" /> 正在解析包并预检…
          </div>
        ) : file ? (
          <div className="space-y-1">
            <p className="text-sm text-ink-dim flex items-center justify-center gap-1.5">
              <FileArchive className="w-4 h-4 text-brand" />
              {file.name}（{(file.size / 1024 / 1024).toFixed(2)} MB）
            </p>
            {(phase === 'select' || phase === 'report') && (
              <p className="text-[11px] text-ink-dim">点击重新选择</p>
            )}
          </div>
        ) : (
          <div className="space-y-1.5">
            <Upload className="w-6 h-6 text-ink-dim mx-auto" />
            <p className="text-sm text-ink-dim">点击选择 afpkg 资源包（.zip）</p>
            <p className="text-[11px] text-ink-dim">从本平台或其他实例导出的包，导入前会先预检并生成报告</p>
          </div>
        )}
      </div>

      {/* 导入选项（预检/报告阶段可调整，调整后重新预检更准确） */}
      {(phase === 'select' || phase === 'report') && (
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="flex items-start gap-2 cursor-pointer select-none p-3 rounded-lg border border-line bg-page">
            <input
              type="checkbox"
              checked={reuseExisting}
              onChange={(e) => setReuseExisting(e.target.checked)}
              className="mt-0.5 accent-brand"
            />
            <span className="text-xs text-ink-dim leading-relaxed">
              复用已有同名资源
              <span className="block text-[11px] text-ink-dim">命中同名时直接把引用指向本实例已有资源，不重复创建</span>
            </span>
          </label>
          <div className="p-3 rounded-lg border border-line bg-page space-y-1.5">
            <span className="text-xs text-ink-dim">名称冲突时</span>
            <div className="flex gap-2">
              {(['rename', 'skip'] as const).map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setConflict(c)}
                  className={`px-2.5 py-1 rounded border text-xs transition cursor-pointer ${
                    conflict === c
                      ? 'border-brand bg-brand-soft text-brand'
                      : 'border-line text-ink-dim hover:text-ink'
                  }`}
                >
                  {c === 'rename' ? '自动改名' : '跳过该项'}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-ink-dim">自动改名生成「原名-imported」；模型的技术标识冲突时始终跳过</p>
          </div>
          {phase === 'report' && (
            <p className="sm:col-span-2 text-[11px] text-sig-wait">
              修改选项后请点击下方「重新预检」以获得准确的报告。
            </p>
          )}
        </div>
      )}

      {/* 预检 / 导入报告 */}
      {report && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="px-2 py-1 rounded bg-brand-soft border border-brand/30 text-brand font-semibold">
              {phase === 'done' ? '已新建' : '将新建'} {report.summary.created}
            </span>
            <span className="px-2 py-1 rounded bg-line text-ink-soft font-semibold">复用 {report.summary.reused}</span>
            {report.summary.skipped > 0 && (
              <span className="px-2 py-1 rounded bg-line text-zinc-400 font-semibold">跳过 {report.summary.skipped}</span>
            )}
            {report.summary.warnings > 0 && (
              <span className="px-2 py-1 rounded bg-sig-wait-soft border border-sig-wait/30 text-sig-wait font-semibold flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" /> 提示 {report.summary.warnings}
              </span>
            )}
            {report.summary.errors > 0 && (
              <span className="px-2 py-1 rounded bg-sig-fail-soft border border-sig-fail/30 text-sig-fail font-semibold flex items-center gap-1">
                <XCircle className="w-3 h-3" /> 失败 {report.summary.errors}
              </span>
            )}
          </div>

          {(['created', 'reused', 'skipped'] as const).map((section) =>
            report[section].length > 0 && (
              <div key={section} className="rounded-lg border border-line bg-page overflow-hidden">
                <div className="px-3 py-1.5 border-b border-line text-[11px] font-bold uppercase tracking-wide text-ink-dim">
                  {section === 'created' ? (phase === 'done' ? '已新建' : '将新建') : section === 'reused' ? '复用已有' : '跳过'}
                </div>
                <ul className="divide-y divide-line/60 max-h-40 overflow-y-auto">
                  {report[section].map((it, i) => (
                    <li key={`${section}-${i}`} className="px-3 py-1.5 flex items-center gap-2 text-xs">
                      {section === 'created' ? (
                        <CheckCircle2 className="w-3 h-3 text-sig-ok shrink-0" />
                      ) : (
                        <span className="w-3 h-3 shrink-0" />
                      )}
                      <span className="text-[11px] px-1.5 py-0.5 rounded bg-line text-ink-soft font-semibold shrink-0">
                        {kindLabel(it.kind)}
                      </span>
                      <span className="text-ink truncate">
                        {it.name}
                        {it.renamed_from && (
                          <span className="text-[11px] text-sig-wait ml-1">（由 {it.renamed_from} 改名）</span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ),
          )}

          {report.warnings.length > 0 && (
            <div className="rounded-lg border border-sig-wait/30 bg-sig-wait-soft/50 overflow-hidden">
              <div className="px-3 py-1.5 border-b border-sig-wait/20 text-[11px] font-bold uppercase tracking-wide text-sig-wait flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" /> 需要注意（敏感凭证不随包迁移，导入后请补填）
              </div>
              <ul className="divide-y divide-sig-wait/20 max-h-48 overflow-y-auto">
                {report.warnings.map((w, i) => (
                  <li key={i} className="px-3 py-1.5 text-xs text-ink-soft leading-relaxed">
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-line text-ink-soft font-semibold mr-1.5">
                      {kindLabel(w.kind)}{w.name ? ` · ${w.name}` : ''}
                    </span>
                    {w.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {report.errors.length > 0 && (
            <div className="rounded-lg border border-sig-fail/30 bg-sig-fail-soft/50 overflow-hidden">
              <div className="px-3 py-1.5 border-b border-sig-fail/20 text-[11px] font-bold uppercase tracking-wide text-sig-fail flex items-center gap-1">
                <XCircle className="w-3 h-3" /> 导入失败项
              </div>
              <ul className="divide-y divide-sig-fail/20">
                {report.errors.map((er, i) => (
                  <li key={i} className="px-3 py-1.5 text-xs text-ink-soft leading-relaxed">
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-line text-ink-soft font-semibold mr-1.5">
                      {kindLabel(er.kind)}{er.name ? ` · ${er.name}` : ''}
                    </span>
                    {er.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {phase === 'importing' && (
        <div className="flex items-center justify-center gap-2 text-ink-dim text-sm py-4">
          <Loader2 className="w-4 h-4 animate-spin" /> 正在导入（含 MCP 连接 discover，可能较慢）…
        </div>
      )}

      {/* 操作栏 */}
      <div className="flex justify-end gap-3 pt-2 border-t border-line">
        {phase === 'done' ? (
          <button
            onClick={() => { setPhase('select'); setFile(null); setReport(null) }}
            className="px-5 py-2 bg-brand hover:bg-brand-hover text-white rounded-lg text-xs font-semibold cursor-pointer"
          >
            继续导入下一个包
          </button>
        ) : phase === 'report' ? (
          <>
            <button
              onClick={() => file && runPreview(file)}
              disabled={busy}
              className="px-4 py-2 border border-line hover:bg-panel text-ink-dim hover:text-ink rounded-lg text-xs font-semibold cursor-pointer disabled:opacity-60"
            >
              重新预检
            </button>
            <button
              onClick={runImport}
              disabled={busy || !report || report.summary.created + report.summary.reused === 0}
              className="px-5 py-2 bg-brand hover:bg-brand-hover text-white rounded-lg text-xs font-semibold cursor-pointer disabled:opacity-60 flex items-center gap-2"
            >
              确认导入
            </button>
          </>
        ) : null}
      </div>
    </div>
  )
}
