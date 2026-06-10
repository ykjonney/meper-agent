/**
 * Settings page — application configuration sections.
 */
import { Button, Switch, Select, Input } from 'antd'
import { SettingOutlined, BellOutlined, LockOutlined, GlobalOutlined, BgColorsOutlined, KeyOutlined, SaveOutlined } from '@ant-design/icons'
import { useTheme, THEMES } from '../contexts/ThemeContext'

const SECTIONS = [
  {
    title: '通用设置',
    icon: <SettingOutlined />,
    fields: [
      { label: '应用名称', type: 'input', value: 'Agent Flow' },
      { label: '默认语言', type: 'select', value: '简体中文', options: ['简体中文', 'English', '日本語'] },
      { label: '时区', type: 'select', value: 'Asia/Shanghai (UTC+8)', options: ['Asia/Shanghai (UTC+8)', 'America/New_York', 'Europe/London'] },
    ],
  },
  {
    title: '通知设置',
    icon: <BellOutlined />,
    fields: [
      { label: '执行完成通知', type: 'switch', value: true },
      { label: '异常告警通知', type: 'switch', value: true },
      { label: '每日摘要邮件', type: 'switch', value: false },
    ],
  },
  {
    title: '安全设置',
    icon: <LockOutlined />,
    fields: [
      { label: '双因素认证', type: 'switch', value: false },
      { label: '会话超时 (分钟)', type: 'select', value: '30', options: ['15', '30', '60', '120'] },
      { label: 'IP 白名单', type: 'input', value: '192.168.1.*' },
    ],
  },
]

export default function SettingsPage() {
  const { t, theme, setTheme } = useTheme()

  return (
    <div className="animate-[fadeIn_0.3s_ease-out] grid grid-cols-3 gap-4">
      {/* Setting sections */}
      <div className="col-span-2 space-y-4">
        {SECTIONS.map((section) => (
          <div key={section.title} className="rounded-xl border border-gray-200 bg-white">
            <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-2">
              <span className="text-base" style={{ color: t.primary }}>{section.icon}</span>
              <span className="font-semibold text-[#0F172A]">{section.title}</span>
            </div>
            <div className="p-5 space-y-4">
              {section.fields.map((field) => (
                <div key={field.label} className="flex items-center justify-between">
                  <span className="text-sm text-[#475569]">{field.label}</span>
                  <div className="w-48">
                    {field.type === 'switch' ? (
                      <Switch checked={field.value as boolean} style={{ background: field.value ? t.primary : undefined }} />
                    ) : field.type === 'select' ? (
                      <Select value={field.value as string} className="w-full" options={(field.options || []).map((o: string) => ({ value: o, label: o }))} />
                    ) : (
                      <Input value={field.value as string} className="w-full" />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}

        {/* Save button */}
        <div className="flex justify-end">
          <Button type="primary" icon={<SaveOutlined />} size="large">保存设置</Button>
        </div>
      </div>

      {/* Right: Theme picker + info */}
      <div className="space-y-4">
        {/* Theme */}
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="flex items-center gap-2 mb-4">
            <BgColorsOutlined style={{ color: t.primary }} />
            <span className="font-semibold text-[#0F172A]">主题色</span>
          </div>
          <div className="flex flex-wrap gap-2 mb-4">
            {THEMES.map((th) => (
              <button
                key={th.key}
                onClick={() => setTheme(th)}
                className={`w-7 h-7 rounded-full transition-all duration-200 ${theme.key === th.key ? 'ring-2 ring-offset-2 scale-110' : 'opacity-60 hover:opacity-100'}`}
                style={{ background: th.primary, ringColor: th.primary }}
                title={th.zhName}
              />
            ))}
          </div>
          <div className="text-xs text-[#64748B]">
            当前: <span style={{ color: t.primary }}>{theme.zhName}</span>
          </div>
          <div className="text-[11px] text-[#94A3B8] mt-1">{theme.vibe}</div>
        </div>

        {/* API Usage */}
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="flex items-center gap-2 mb-4">
            <KeyOutlined style={{ color: t.primary }} />
            <span className="font-semibold text-[#0F172A]">API 用量</span>
          </div>
          <div className="space-y-3">
            {[
              { label: 'GPT-4', used: 84700, total: 100000 },
              { label: 'Claude 3', used: 42300, total: 100000 },
              { label: 'Gemini', used: 12500, total: 50000 },
            ].map((api) => (
              <div key={api.label}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-[#475569]">{api.label}</span>
                  <span className="text-[#94A3B8]">{(api.used / 1000).toFixed(1)}K / {(api.total / 1000).toFixed(0)}K</span>
                </div>
                <div className="h-1.5 bg-[#F1F5F9] rounded-full overflow-hidden">
                  <div className="h-full rounded-full transition-all duration-500" style={{ width: `${(api.used / api.total) * 100}%`, background: t.primary }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
