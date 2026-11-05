/**
 * KnowledgePage — 知识库工作区（预览稿视觉 + 真实 knowledgeApi.list）。
 * 反向引用（被 N 个 Agent 挂载）= 前端从 agent.knowledge_base_ids 统计。
 * 详情页（分片/命中测试）P4.5。
 */
import { useQuery } from '@tanstack/react-query';
import { knowledgeApi } from '../services/knowledge-api';
import { agentApi } from '../services/agent-api';
import { FlowMark } from '../components/shell/FlowMark';

const CSS = `
.kb { height:100%; overflow-y:auto; background:var(--color-canvas); font-family:-apple-system,'PingFang SC','Segoe UI',sans-serif; font-size:14px; color:#1E1B2E; }
.kb-inner { padding:14px; display:flex; gap:14px; align-items:flex-start; }
.K-card { background:#fff; border-radius:13px; padding:14px 17px; box-shadow:0 1px 3px rgba(42,38,64,.05); }
.K-pill { font-size:10px; border-radius:99px; padding:2px 10px; font-weight:700; display:inline-block; }
.K-pg { background:#E8F6EE; color:#1F8A55; } .K-pr { background:#EFEAFD; color:#6D4AE0; }
.K-pw { background:#FDF3E1; color:#B97A0F; } .K-pe { background:#FEE2E2; color:#DC2626; }
.K-pd { background:#F1EFF8; color:#8A85A3; }
.K-bp { background:linear-gradient(135deg,#8B5CF6,#6D4AE0); color:#fff; border-radius:8px; padding:6px 18px; font-size:12px; font-weight:700; display:inline-block; cursor:pointer; }
.K-meter { height:5px; background:#F1EEF9; border-radius:99px; overflow:hidden; }
.K-meter i { display:block; height:100%; background:linear-gradient(90deg,#8B5CF6,#6D4AE0); border-radius:99px; }
.K-av { border-radius:10px; display:flex; align-items:center; justify-content:center; flex:none; font-size:16px; }
`;

function BuildPill({ status }: { status: string }) {
  if (status === 'success' || status === 'completed') return <span className="K-pill K-pg">就绪</span>;
  if (status === 'building' || status === 'running' || status === 'pending')
    return <span className="K-pill K-pw">构建中</span>;
  if (status === 'failed' || status === 'error') return <span className="K-pill K-pe">构建失败</span>;
  return <span className="K-pill K-pd">{status || '未构建'}</span>;
}

export function KnowledgePage() {
  const { data, isLoading } = useQuery({
    queryKey: ['knowledge-bases'], queryFn: () => knowledgeApi.list({ page_size: 50 }),
  });
  const { data: allAgents } = useQuery({
    queryKey: ['agents', 'kb-ref'], queryFn: () => agentApi.list({ status: 'all', page_size: 50 }),
  });
  const kbs = data?.items ?? [];
  const refCount = (kbId: string) =>
    (allAgents?.items ?? []).filter((a) => a.knowledge_base_ids.includes(kbId)).length;

  return (
    <div className="kb">
      <style>{CSS}</style>
      <div className="kb-inner">
        {/* 列表 */}
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 13 }}>
            <b style={{ fontSize: 16, fontWeight: 800 }}>知识库</b>
            <span className="K-bp" style={{ marginLeft: 'auto' }} title="P4.5">＋ 新建</span>
          </div>
          {isLoading ? (
            <div style={{ padding: 40, textAlign: 'center', color: '#9A95B0' }}>加载中…</div>
          ) : kbs.length === 0 ? (
            <div className="K-card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, padding: '60px 20px', color: '#9A95B0' }}>
              <FlowMark size={32} />
              <span style={{ fontSize: 13 }}>暂无知识库</span>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {kbs.map((kb) => (
                <div key={kb.id} className="K-card" style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '13px 16px' }}>
                  <div className="K-av" style={{ width: 36, height: 36, background: kb.type === 'vector' ? '#E8F6EE' : '#EFEAFD' }}>
                    <FlowMark size={15} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <b style={{ fontSize: 13.5 }}>{kb.name}</b>
                    <div style={{ fontSize: 11, color: '#9A95B0' }}>
                      {kb.type === 'vector' ? '向量' : '文档树'} · {kb.file_count} 文件 · {(kb.total_size / 1024 / 1024).toFixed(1)} MB · {new Date(kb.updated_at).toLocaleDateString('zh-CN')}
                    </div>
                  </div>
                  {refCount(kb.id) > 0 && (
                    <span className="K-pill K-pr">被 {refCount(kb.id)} 个 Agent 挂载</span>
                  )}
                  <BuildPill status={kb.last_build_status} />
                </div>
              ))}
            </div>
          )}
        </div>
        {/* 详情示意（P4.5 接分片/命中测试） */}
        <div style={{ flex: 1.5, background: '#fff', border: '1px solid #EFEDF7', borderRadius: 13, padding: '16px 19px', alignSelf: 'flex-start' }}>
          <div style={{ textAlign: 'center', padding: '40px 12px', color: '#B6B1C9', fontSize: 12.5 }}>
            <FlowMark size={28} />
            <div style={{ marginTop: 8 }}>从左侧选择知识库查看分片与文档</div>
            <div style={{ marginTop: 4, fontSize: 11 }}>详情页（分片/源文档/命中测试）P4.5 接入</div>
          </div>
        </div>
      </div>
    </div>
  );
}
