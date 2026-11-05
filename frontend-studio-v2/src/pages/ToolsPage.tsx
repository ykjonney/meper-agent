/**
 * ToolsPage — 工具生态（预览稿视觉 + 真实数据）。
 * 五 Tab：内置（toolsApi.listBuiltins）/ 自定义（userToolsApi.listEnabled）/
 * 技能（userSkillsApi.list）/ MCP（mcpApi.list）/ 外部授权（myAppAuthorizationsApi）。
 * 新建/编辑弹窗 P4.5。
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toolsApi } from '../services/tools-api';
import { userToolsApi } from '../services/user-tools-api';
import { userSkillsApi } from '../services/user-skills-api';
import { mcpApi } from '../services/mcp-api';
import { myAppAuthorizationsApi } from '../services/my-app-authorizations-api';
import { agentApi } from '../services/agent-api';
import { FlowMark } from '../components/shell/FlowMark';

const CSS = `
.tl { height:100%; overflow-y:auto; background:var(--color-canvas); font-family:-apple-system,'PingFang SC','Segoe UI',sans-serif; font-size:14px; color:#1E1B2E; }
.tl-inner { padding:17px 22px; }
.tl * { box-sizing:border-box; }
.K-card { background:#fff; border-radius:13px; padding:14px 17px; box-shadow:0 1px 3px rgba(42,38,64,.05); }
.K-pill { font-size:10px; border-radius:99px; padding:2px 10px; font-weight:700; display:inline-block; }
.K-pg { background:#E8F6EE; color:#1F8A55; } .K-pr { background:#EFEAFD; color:#6D4AE0; }
.K-pw { background:#FDF3E1; color:#B97A0F; } .K-pe { background:#FEE2E2; color:#DC2626; }
.K-pd { background:#F1EFF8; color:#8A85A3; }
.K-bp { background:linear-gradient(135deg,#8B5CF6,#6D4AE0); color:#fff; border-radius:8px; padding:6px 18px; font-size:12px; font-weight:700; display:inline-block; cursor:pointer; }
.K-bg { border:1px solid #DDD3F8; color:#6D4AE0; border-radius:8px; padding:6px 18px; font-size:12px; font-weight:700; background:#fff; display:inline-block; cursor:pointer; }
.K-tabs { display:flex; gap:4px; background:#ECE8F8; border-radius:11px; padding:4px; }
.K-tab { padding:5px 17px; border-radius:9px; font-size:13px; color:#8A85A3; font-weight:600; cursor:pointer; }
.K-tab.on { background:#fff; color:#6D4AE0; box-shadow:0 1px 3px rgba(42,38,64,.08); }
.K-av { border-radius:10px; display:flex; align-items:center; justify-content:center; flex:none; font-size:15px; color:#fff; }
`;

export function ToolsPage() {
  const [tab, setTab] = useState('builtin');

  const { data: builtins, isLoading: bl } = useQuery({
    queryKey: ['tools-builtin'], queryFn: () => toolsApi.listBuiltins(), enabled: tab === 'builtin',
  });
  const { data: customs, isLoading: cu } = useQuery({
    queryKey: ['tools-custom'], queryFn: () => userToolsApi.listEnabled(), enabled: tab === 'custom',
  });
  const { data: skills, isLoading: sk } = useQuery({
    queryKey: ['skills'], queryFn: () => userSkillsApi.list(), enabled: tab === 'skills',
  });
  const { data: mcp, isLoading: mc } = useQuery({
    queryKey: ['mcp'], queryFn: () => mcpApi.list({}), enabled: tab === 'mcp',
  });
  const { data: auths, isLoading: au } = useQuery({
    queryKey: ['my-authorizations'], queryFn: () => myAppAuthorizationsApi.get(), enabled: tab === 'auth',
  });
  const { data: allAgents } = useQuery({
    queryKey: ['agents', 'tool-ref'], queryFn: () => agentApi.list({ status: 'all', page_size: 50 }),
  });
  // "被 N Agent 使用"（前端从 Agent 挂载字段统计）
  const usedBy = (id: string) => (allAgents?.items ?? []).filter((a) =>
    a.custom_tools.some((c) => c.tool_id === id) || a.skill_ids.includes(id) || a.mcp_connection_ids.includes(id),
  ).length;

  const loading = bl || cu || sk || mc || au;

  return (
    <div className="tl">
      <style>{CSS}</style>
      <div className="tl-inner">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 15 }}>
          <b style={{ fontSize: 18, fontWeight: 800 }}>工具生态</b>
          <div className="K-tabs">
            <span className={`K-tab ${tab === 'builtin' ? 'on' : ''}`} onClick={() => setTab('builtin')}>内置{Array.isArray(builtins) ? ` · ${builtins.length}` : ''}</span>
            <span className={`K-tab ${tab === 'custom' ? 'on' : ''}`} onClick={() => setTab('custom')}>自定义{Array.isArray(customs) ? ` · ${customs.length}` : ''}</span>
            <span className={`K-tab ${tab === 'skills' ? 'on' : ''}`} onClick={() => setTab('skills')}>技能{Array.isArray(skills) ? ` · ${skills.length}` : ''}</span>
            <span className={`K-tab ${tab === 'mcp' ? 'on' : ''}`} onClick={() => setTab('mcp')}>MCP 接入{mcp ? ` · ${mcp.total}` : ''}</span>
            <span className={`K-tab ${tab === 'auth' ? 'on' : ''}`} onClick={() => setTab('auth')}>外部授权</span>
          </div>
          <span className="K-bp" style={{ marginLeft: 'auto' }} title="P4.5">＋ 新建</span>
        </div>

        {loading ? (
          <div style={{ padding: 40, textAlign: 'center', color: '#9A95B0' }}>加载中…</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(300px,1fr))', gap: 12 }}>
            {((tab === 'builtin' && (!builtins || builtins.length === 0)) ||
              (tab === 'custom' && (!customs || customs.length === 0)) ||
              (tab === 'skills' && (!skills || skills.length === 0)) ||
              (tab === 'mcp' && (!mcp || mcp.total === 0)) ||
              (tab === 'auth' && (!auths || (auths.bindings ?? []).length === 0))) && (
              <div className="K-card" style={{ gridColumn: '1 / -1', padding: '60px 20px', textAlign: 'center', color: '#B6B1C9', fontSize: 13 }}>
                <FlowMark size={28} />
                <div style={{ marginTop: 10 }}>暂无条目 — 点右上角「＋ 新建」开始</div>
              </div>
            )}
            {/* 内置 */}
            {tab === 'builtin' && (builtins ?? []).map((b) => (
              <div key={String(b.name)} className="K-card">
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <div className="K-av" style={{ width: 34, height: 34, background: '#EFEAFD', color: '#6D4AE0' }}>
                    <FlowMark size={15} />
                  </div>
                  <b style={{ fontSize: 13 }}>{String(b.name ?? '')}</b>
                </div>
                <div style={{ fontSize: 11.5, color: '#8A85A3', margin: '6px 0' }}>{String(b.description ?? '')}</div>
              </div>
            ))}
            {/* 自定义 */}
            {tab === 'custom' && (customs ?? []).map((t) => (
              <div key={String(t.id ?? t.name)} className="K-card">
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <div className="K-av" style={{ width: 34, height: 34, background: '#E8F6EE', color: '#1F8A55' }}>
                    <FlowMark size={15} />
                  </div>
                  <b style={{ fontSize: 13 }}>{String(t.name ?? '')}</b>
                </div>
                <div style={{ fontSize: 11.5, color: '#8A85A3', margin: '6px 0' }}>{String(t.description ?? '')}</div>
                <div style={{ display: 'flex', gap: 6, fontSize: 10.5 }}>
                  <span style={{ color: '#B6B1C9' }}>{usedBy(String(t.id)) > 0 ? `被 ${usedBy(String(t.id))} Agent 使用` : '未挂载'}</span>
                  <span className="K-bg" style={{ marginLeft: 'auto', fontSize: 10.5, padding: '2px 10px' }}>详情</span>
                </div>
              </div>
            ))}
            {/* 技能 */}
            {tab === 'skills' && (skills ?? []).map((k) => (
              <div key={String(k.id ?? k.name)} className="K-card">
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <div className="K-av" style={{ width: 34, height: 34, background: 'linear-gradient(135deg,#8B5CF6,#6D4AE0)' }}>
                    <FlowMark size={15} />
                  </div>
                  <b style={{ fontSize: 13 }}>{String(k.name ?? '')}</b>
                  <span className={`K-pill ${String(k.status) === 'published' ? 'K-pg' : 'K-pd'}`}>{String(k.status) === 'published' ? '已发布' : String(k.status)}</span>
                </div>
                <div style={{ fontSize: 11.5, color: '#8A85A3', margin: '6px 0' }}>{String(k.description ?? '')}</div>
                <div style={{ display: 'flex', gap: 6, fontSize: 10.5 }}>
                  <span style={{ color: '#B6B1C9' }}>{usedBy(String(k.id)) > 0 ? `被 ${usedBy(String(k.id))} Agent 使用` : '未挂载'}</span>
                  <span className="K-bg" style={{ marginLeft: 'auto', fontSize: 10.5, padding: '2px 10px' }}>详情</span>
                </div>
              </div>
            ))}
            {/* MCP */}
            {tab === 'mcp' && (mcp?.items ?? []).map((c) => (
              <div key={c.id} className="K-card">
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <div className="K-av" style={{ width: 34, height: 34, background: '#FCEBF5', color: '#C02690' }}>
                    <FlowMark size={15} />
                  </div>
                  <b style={{ fontSize: 13 }}>{c.name}</b>
                  <span className={`K-pill ${c.status === 'connected' ? 'K-pg' : 'K-pd'}`}>{c.status === 'connected' ? '已连接' : c.status}</span>
                </div>
                <div style={{ fontSize: 11.5, color: '#8A85A3', margin: '6px 0' }}>{c.description || c.url}</div>
                <div style={{ display: 'flex', gap: 6, fontSize: 10.5 }}>
                  <span style={{ color: '#B6B1C9' }}>{c.tool_count} 个动作{usedBy(c.id) > 0 ? ` · ${usedBy(c.id)} Agent 挂载` : ''}</span>
                  <span className="K-bg" style={{ marginLeft: 'auto', fontSize: 10.5, padding: '2px 10px' }}>详情</span>
                </div>
              </div>
            ))}
            {/* 外部授权 */}
            {tab === 'auth' && (
              (auths?.bindings ?? []).length === 0 ? (
                <div style={{ gridColumn: '1 / -1', padding: '40px 0', textAlign: 'center', color: '#B6B1C9', fontSize: 12.5 }}>暂无已授权应用</div>
              ) : (
                (auths?.bindings ?? []).map((bnd) => (
                  <div key={bnd.app_id} className="K-card">
                    <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                      <div className="K-av" style={{ width: 34, height: 34, background: '#E8F0FE', color: '#2563EB' }}>
                        <FlowMark size={15} />
                      </div>
                      <b style={{ fontSize: 13 }}>{bnd.app_name}</b>
                      <span className="K-pill K-pg">已授权</span>
                    </div>
                    <div style={{ fontSize: 11.5, color: '#8A85A3', margin: '6px 0' }}>账号：{bnd.username}</div>
                    <div style={{ display: 'flex', gap: 6, fontSize: 10.5 }}>
                      <span className="K-bg" style={{ marginLeft: 'auto', fontSize: 10.5, padding: '2px 10px' }}>管理</span>
                    </div>
                  </div>
                ))
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}
