/**
 * SettingsPage — 系统设置（多权限域容器）。
 *
 * 导航入口权限 = 各 Tab 权限的并集（App.tsx 的 settings 导航项
 * permission: ['settings:manage', 'channel:read']，任一满足即可见），
 * 页内每个 Tab 独立门控（判 permission 不判 role，PERMISSIONS.md）：
 * - 外部接入 / 语音设置 / 全局参数 → settings:manage（后端 apikey/settings/voice_config 同键）
 * - 消息渠道 → channel:read（后端 channels 路由级同键；
 *   写操作另需 channel:write，在 ChannelsPage 内门控）
 * developer 默认无 settings:manage 但有 channel 读写——仍能从导航进入
 * 本页，只看到「消息渠道」Tab。
 */
import { useState } from 'react';
import { Key, Mic, MessagesSquare, Sliders } from 'lucide-react';
import { usePermission } from '../hooks/use-permission';
import { SegmentedTabs, type SegmentedTabItem } from './ui/tabs';
import { ExternalAccessPage, RuntimeParamsPage } from './SystemSettings';
import { VoiceConfigPage } from './voice/VoiceConfigPage';
import { ChannelsPage } from './ChannelsPage';

type Tab = 'general' | 'params' | 'voice' | 'channels';

interface Props {
  theme: 'dark' | 'light';
}

export function SettingsPage({ theme }: Props) {
  const canManageSettings = usePermission('settings:manage');
  const canReadChannels = usePermission('channel:read');
  const [tab, setTab] = useState<Tab>('general');

  const allTabs: SegmentedTabItem<Tab>[] = [
    { id: 'general', label: '外部接入', icon: Key },
    { id: 'voice', label: '语音设置', icon: Mic },
    { id: 'params', label: '全局参数', icon: Sliders },
    { id: 'channels', label: '消息渠道', icon: MessagesSquare },
  ];
  const tabs = allTabs.filter((t) => (t.id === 'channels' ? canReadChannels : canManageSettings));

  if (tabs.length === 0) return null;

  // 渲染期兜底：当前 Tab 被权限过滤掉时落到第一个可见 Tab
  // （如仅渠道权限的用户默认态 general 不可见）——与 App.tsx 导航回退同语义
  const active: Tab = tabs.some((t) => t.id === tab) ? tab : tabs[0].id;

  return (
    <div className="h-full min-h-0 flex flex-col gap-4">
      <div className="shrink-0">
        <SegmentedTabs tabs={tabs} value={active} onChange={(id: Tab) => setTab(id)} theme={theme} />
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-custom pt-1 pb-2 pr-1.5">
        <div className={active === 'voice' ? 'max-w-3xl' : undefined}>
          {active === 'general' && <ExternalAccessPage />}
          {active === 'voice' && <VoiceConfigPage theme={theme} />}
          {active === 'params' && <RuntimeParamsPage />}
          {active === 'channels' && <ChannelsPage />}
        </div>
      </div>
    </div>
  );
}
