/**
 * AgentsPage — 智能体工作区（预览稿视觉 + 真实数据）。
 * Tab：我的智能体（agentApi.list all）/ 工作路线（workflowsApi.list）/ 组织市场（P4.5）。
 * 编辑器 P4.5（ConfigModal 同理）。
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { agentApi } from '../services/agent-api';
import { workflowsApi } from '../services/workflows-api';
import { FlowMark } from '../components/shell/FlowMark';

const CSS = `
.aw { height:100%; overflow-y:auto; background:var(--color-canvas); font-family:-apple-system,'PingFang SC','Segoe UI',sans-serif; font-size:14px; color:#1E1B2E; }
.aw-inner { padding:14px; }
.K-card { background:#fff; border-radius:13px; padding:14px 17px; box-shadow:0 1px 3px rgba(42,38,64,.05); }
.K-pill { font-size:10px; border-radius:99px; padding:2px 10px; font-weight:700; display:inline-block; }
.K-pg { background:#E8F6EE; color:#1F8A55; } .K-pr { background:#EFEAFD; color:#6D4AE0; }
.K-pd { background:#F1EFF8; color:#8A85A3; }
.K-bp { background:linear-gradient(135deg,#8B5CF6,#6D4AE0); color:#fff; border-radius:8px; padding:5px 15px; font-size:12px; font-weight:700; display:inline-block; cursor:pointer; }
.K-bg { border:1px solid #DDD3F8; color:#6D4AE0; border-radius:8px; padding:5px 15px; font-size:12px; font-weight:700; background:#fff; display:inline-block; cursor:pointer; }
.K-tabs { display:flex; gap:4px; background:#ECE8F8; border-radius:11px; padding:4px; }
.K-tab { padding:5px 17px; border-radius:9px; font-size:13px; color:#8A85A3; font-weight:600; cursor:pointer; }
.K-tab.on { background:#fff; color:#6D4AE0; box-shadow:0 1px 3px rgba(42,38,64,.08); }
.ag-srch { background:#fff; border:1px solid #E2DCF5; border-radius:10px; padding:6px 14px; font-size:13px; color:#B6B1C9; width:200px; outline:none; }
.ag-av { border-radius:10px; display:flex; align-items:center; justify-content:center; flex:none; }
.op { font-size:11.5px; color:#6D4AE0; font-weight:600; background:#F6F4FC; border-radius:7px; padding:3px 11px; cursor:pointer; }
`;

export function AgentsPage() {
  const nav = useNavigate();
  const [tab, setTab] = useState('agents');
  const [kw, setKw] = useState('');
  const { data, isLoading } = useQuery({
    queryKey: ['agents', 'workspace'],
    queryFn: () => agentApi.list({ status: 'all', page_size: 50 }),
  });
  const { data: wf } = useQuery({
    queryKey: ['workflows', 'workspace'],
    queryFn: () => workflowsApi.list({ page_size: 50 }),
    enabled: tab === 'flows',
  });
  const agents = (data?.items ?? []).filter((a) => !kw || a.name.toLowerCase().includes(kw.toLowerCase()));

  return (
    <div className="aw">
      <style>{CSS}</style>
      <div className="aw-inner">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
          <h2 style={{ margin: 0, fontSize: 19, fontWeight: 800 }}>智能体</h2>
          <div className="K-tabs">
            <span className={`K-tab ${tab === 'agents' ? 'on' : ''}`} onClick={() => setTab('agents')}>我的智能体{data?.total !== undefined ? ` · ${data.total}` : ''}</span>
            <span className={`K-tab ${tab === 'flows' ? 'on' : ''}`} onClick={() => setTab('flows')}>工作路线{wf?.total !== undefined ? ` · ${wf.total}` : ''}</span>
            <span className={`K-tab ${tab === 'market' ? 'on' : ''}`} onClick={() => setTab('market')}>组织市场</span>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center' }}>
            <input className="ag-srch" value={kw} onChange={(e) => setKw(e.target.value)} placeholder="🔍 搜索智能体…" />
            <span className="K-bg" title="P4.5">✨ AI 生成</span>
            <span className="K-bp" onClick={() => nav('/agents/new')}>＋ 新建</span>
          </div>
        </div>

        {tab === 'agents' && (
          isLoading ? (
            <div style={{ padding: 40, textAlign: 'center', color: '#9A95B0' }}>加载中…</div>
          ) : agents.length === 0 ? (
            <div className="K-card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, padding: '60px 20px', color: '#9A95B0' }}>
              <FlowMark size={32} />
              <span style={{ fontSize: 13 }}>暂无智能体 — 新建第一个数字员工</span>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(300px,1fr))', gap: 13 }}>
              {agents.map((a) => (
                <div key={a.id} className="K-card" style={{ display: 'flex', flexDirection: 'column', gap: 7, position: 'relative', padding: '14px 16px' }}>
                  <span className={`K-pill ${a.status === 'published' ? 'K-pg' : 'K-pd'}`} style={{ position: 'absolute', top: 13, right: 13 }}>
                    {a.status === 'published' ? '已发布' : a.status === 'draft' ? '草稿' : a.status}
                  </span>
                  <div style={{ display: 'flex', gap: 11, alignItems: 'center' }}>
                    <div className="ag-av" style={{ width: 41, height: 41, background: a.avatar ? '#EFEAFD' : 'linear-gradient(135deg,#8B5CF6,#6D4AE0)', fontSize: 19 }}>
                      {a.avatar || <FlowMark size={16} />}
                    </div>
                    <div style={{ minWidth: 0, paddingRight: 60 }}>
                      <b style={{ fontSize: 14.5, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.name}</b>
                      <span style={{ fontSize: 11, color: '#9A95B0' }}>{new Date(a.updated_at).toLocaleDateString('zh-CN')} 更新</span>
                    </div>
                  </div>
                  <div style={{ fontSize: 12, color: '#8A85A3', lineHeight: 1.5, height: 36, overflow: 'hidden' }}>{a.description || '—'}</div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                    {a.skill_ids.length > 0 && <span className="K-pill K-pr">技能 ×{a.skill_ids.length}</span>}
                    {a.knowledge_base_ids.length > 0 && <span className="K-pill K-pr">知识库 ×{a.knowledge_base_ids.length}</span>}
                    {a.mcp_connection_ids.length > 0 && <span className="K-pill K-pr">MCP ×{a.mcp_connection_ids.length}</span>}
                    {a.subagent_ids.length > 0 && <span className="K-pill K-pr">子 Agent ×{a.subagent_ids.length}</span>}
                    {a.voice_enabled && <span className="K-pill K-pg">语音</span>}
                  </div>
                  <div style={{ display: 'flex', gap: 7, borderTop: '1px solid #F4F2FA', paddingTop: 8, marginTop: 3 }}>
                    <span className="op" onClick={() => nav(`/chat?agent=${a.id}`)}>对话</span>
                    <span className="op" onClick={() => nav(`/agents/${a.id}/edit`)}>编辑</span>
                    <span className="op">⋯</span>
                  </div>
                </div>
              ))}
            </div>
          )
        )}

        {tab === 'flows' && (
          isLoading ? (
            <div style={{ padding: 40, textAlign: 'center', color: '#9A95B0' }}>加载中…</div>
          ) : (wf?.items ?? []).length === 0 ? (
            <div className="K-card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, padding: '60px 20px', color: '#9A95B0' }}>
              <FlowMark size={32} />
              <span style={{ fontSize: 13 }}>暂无工作路线</span>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(300px,1fr))', gap: 13 }}>
              {(wf?.items ?? []).map((w) => (
                <div key={w.id} className="K-card" style={{ display: 'flex', flexDirection: 'column', gap: 7, padding: '14px 16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <b style={{ fontSize: 13.5, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{w.name}</b>
                    <span className="K-pill K-pr" style={{ fontFamily: 'Menlo,monospace' }}>v{w.version}</span>
                  </div>
                  <div style={{ fontSize: 12, color: '#8A85A3', lineHeight: 1.5, height: 36, overflow: 'hidden' }}>{w.description || '—'}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, borderTop: '1px solid #F4F2FA', paddingTop: 8 }}>
                    <span style={{ fontSize: 11, color: '#9A95B0' }}>{w.node_count} 节点</span>
                    <span className={`K-pill ${w.status === 'published' ? 'K-pg' : 'K-pd'}`} style={{ marginLeft: 'auto' }}>{w.status}</span>
                  </div>
                </div>
              ))}
            </div>
          )
        )}

        {tab === 'market' && (
          <div className="K-card" style={{ padding: '60px 20px', textAlign: 'center', color: '#9A95B0', fontSize: 13 }}>
            组织市场 — 即将上线
          </div>
        )}
      </div>
    </div>
  );
}
