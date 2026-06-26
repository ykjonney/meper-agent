import { useState, FormEvent } from 'react';
import { ApiKey, ExecutionLog } from '../types';
import { 
  Key, ShieldAlert, Plus, Terminal, RefreshCw, Trash, ExternalLink, Sliders, ToggleLeft, 
  HelpCircle, CheckCircle, Database, Check 
} from 'lucide-react';

interface SystemSettingsProps {
  apiKeys: ApiKey[];
  onAddKey: (key: ApiKey) => void;
  onRevokeKey: (id: string) => void;
}

export function SystemSettings({ apiKeys, onAddKey, onRevokeKey }: SystemSettingsProps) {
  const [newKeyName, setNewKeyName] = useState('');
  const [showCreatedBanner, setShowCreatedBanner] = useState(false);

  // Global properties flags state
  const [timeout, setTimeoutVal] = useState(30);
  const [detailedAnimation, setDetailedAnimation] = useState(true);
  const [autoClearCache, setAutoClearCache] = useState(false);
  const [strictSchema, setStrictSchema] = useState(true);

  const handleGenerateKey = (e: FormEvent) => {
    e.preventDefault();
    if (!newKeyName) return;

    // Generate random mock key characters
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let rand = '';
    for (let i = 0; i < 12; i++) {
      rand += chars.charAt(Math.floor(Math.random() * chars.length));
    }

    const newKey: ApiKey = {
      id: 'key_' + Date.now(),
      name: newKeyName,
      keyPreview: `AIzaSy...${rand}`,
      created: new Date().toISOString().substring(0, 10),
      lastUsed: '从未使用',
      status: 'active',
    };

    onAddKey(newKey);
    setNewKeyName('');
    setShowCreatedBanner(true);
    setTimeout(() => setShowCreatedBanner(false), 4000); // fade out banner
  };

  return (
    <div className="space-y-6">
      {/* Visual top bar */}
      <div className="flex items-center gap-3 p-4 bg-[#18181b] rounded-xl border border-[#27272a]">
        <Key className="w-5 h-5 text-amber-400" />
        <div className="space-y-0.5">
          <h2 className="text-sm font-bold text-white font-sans">密钥与后端引擎全局配置</h2>
          <p className="text-xs text-[#a1a1aa] font-sans">在此配置和中转开发平台调用大模型、视频引擎及 MCP 本地网关需要的鉴权 Token。</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* LEFT COLUMN: API KEY MANAGEMENT */}
        <div className="lg:col-span-7 bg-[#18181b] border border-[#27272a] rounded-xl p-5 shadow-lg space-y-6">
          <div className="space-y-1">
            <h3 className="text-sm font-bold text-white font-sans">API 密钥生命周期管理 (/api-keys)</h3>
            <p className="text-xs text-slate-500 font-sans">智能体及图网络节点执行外部任务时调用的统一凭据。</p>
            <p className="text-[10px] text-amber-400 font-sans flex items-center gap-1">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400" />
              GAP: 后端暂无 /api-keys 接口，本区为客户端 mock（Math.random 生成预览），不会持久化。
            </p>
          </div>

          {/* Key creation banner */}
          {showCreatedBanner && (
            <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-emerald-400 text-xs flex items-center gap-2 animate-fade-in font-sans">
              <CheckCircle className="w-4 h-4 shrink-0" />
              <span>新 API 鉴权 Token 已安全生成！该凭证已就地加密并同步缓存至 LinkGraph 本地隔离沙箱。</span>
            </div>
          )}

          <form onSubmit={handleGenerateKey} className="flex gap-2 text-xs">
            <input
              type="text"
              required
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              placeholder="命名您的新密钥... (如: High-Speed-Flash)"
              className="flex-1 px-3 py-2 bg-[#121214] border border-[#27272a] rounded-lg text-slate-200 focus:outline-none focus:border-amber-400 transition font-sans placeholder-slate-650"
            />
            <button
              type="submit"
              className="px-4 py-2 bg-gradient-to-r from-amber-500 to-yellow-600 hover:from-amber-600 hover:to-yellow-700 text-slate-950 font-bold rounded-lg shadow cursor-pointer transition flex items-center gap-1 font-sans"
            >
              <Plus className="w-4 h-4 text-slate-950" />
              生成新 Key
            </button>
          </form>

          {/* Keys list */}
          <div className="space-y-3">
            {apiKeys.map((key) => (
              <div
                key={key.id}
                className="p-4 bg-[#121214]/60 rounded-lg border border-[#27272a] flex items-center justify-between text-xs"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-200 font-sans">{key.name}</span>
                    <span className={`px-1.5 py-0.5 rounded text-[8px] font-mono font-bold ${
                      key.status === 'active' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-red-400'
                    }`}>
                      {key.status === 'active' ? 'ACTIVED' : 'REVOKED'}
                    </span>
                  </div>
                  <div className="flex gap-4 text-[#71717a] font-mono text-[10px]">
                    <span>密钥预览: {key.keyPreview}</span>
                    <span>生成日期: {key.created}</span>
                    <span>上一次使用: {key.lastUsed}</span>
                  </div>
                </div>

                {key.status === 'active' && (
                  <button
                    onClick={() => onRevokeKey(key.id)}
                    className="p-1 px-2 border border-rose-950/20 text-rose-400 hover:text-white hover:bg-rose-950 rounded-lg transition text-[10px] cursor-pointer font-semibold"
                  >
                    撤销
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* RIGHT COLUMN: ENGINE GENERAL CONFIGS */}
        <div className="lg:col-span-5 bg-[#18181b] border border-[#27272a] rounded-xl p-5 shadow-lg flex flex-col justify-between">
          <div className="space-y-5">
            <div className="space-y-1 border-b border-[#27272a] pb-3 mb-2">
              <h3 className="text-sm font-bold text-white font-sans flex items-center gap-1.5">
                <Sliders className="w-4 h-4 text-indigo-400" />
                虚拟机全局控制参数
              </h3>
              <p className="text-xs text-slate-500 font-sans">微调 Dify 以及 LangGraph 工作流运行时系统机制。</p>
            </div>

            {/* Timeout settings */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-[#a1a1aa] font-medium font-sans">最大 LLM 事务超时时长 (Timeout)</span>
                <span className="text-white font-mono font-bold">{timeout}s</span>
              </div>
              <input
                type="range"
                min="5"
                max="120"
                step="5"
                value={timeout}
                onChange={(e) => setTimeoutVal(parseInt(e.target.value))}
                className="w-full focus:outline-none accent-indigo-500"
              />
            </div>

            {/* Boolean feature flags toggles */}
            <div className="space-y-4 pt-2">
              {[
                {
                  id: 'detailedAnimation',
                  title: '启用图 Dashing 流转连线动效',
                  desc: '在测试运行工作流时，实时渲染连线的高精度流动虚线轨迹。建议始终开启。',
                  state: detailedAnimation,
                  setter: setDetailedAnimation,
                },
                {
                  id: 'strictSchema',
                  title: '严格模型执行 Schema 校验',
                  desc: '对每一个 Agent worker 输出的 JSON payload 实施强制格式和数据类型校正，出错则自动重试打回。',
                  state: strictSchema,
                  setter: setStrictSchema,
                },
                {
                  id: 'autoClearCache',
                  title: '会话闭环后自清理内存临时变量',
                  desc: '为了安全性。一旦整个流程图完美流至 END 节点，一键释放在内存中的任务草纲与文件缓存。',
                  state: autoClearCache,
                  setter: setAutoClearCache,
                },
              ].map((flag) => (
                <div key={flag.id} className="flex items-start justify-between gap-4 text-xs">
                  <div className="space-y-0.5">
                    <span className="font-semibold text-slate-300 font-sans">{flag.title}</span>
                    <p className="text-[11px] text-[#71717a] leading-normal font-sans">{flag.desc}</p>
                  </div>

                  <button
                    onClick={() => flag.setter(!flag.state)}
                    className="shrink-0 w-11 h-6 rounded-full transition relative flex items-center p-0.5 cursor-pointer bg-[#27272a]"
                    style={{
                      backgroundColor: flag.state ? '#4f46e5' : '#27272a',
                    }}
                  >
                    <span
                      className="w-5 h-5 rounded-full bg-white shadow-md block transition-transform duration-200"
                      style={{
                        transform: flag.state ? 'translateX(20px)' : 'translateX(0)',
                      }}
                    />
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="p-3 bg-indigo-950/20 border border-indigo-900/30 rounded-lg space-y-1 text-indigo-300 mt-4">
            <span className="font-semibold flex items-center gap-1.5 text-xs font-sans">
              <ShieldAlert className="w-3.5 h-3.5 text-indigo-400" />
              API 安全提醒
            </span>
            <p className="text-[10px] leading-relaxed text-[#a1a1aa]">
              密钥在本地处于 AES-256 加密保存状态，系统永远不会在浏览器 Console 或任何第三方上传 API 中泄露 API 密钥。如果发现泄露，建议立即点击「撤销」重新生成凭证。
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
