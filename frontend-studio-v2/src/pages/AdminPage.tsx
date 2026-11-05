/**
 * AdminPage — 严格照抄 all-pages-review ⑧ 翻译（子导航 + 用户权限表）。
 * 数据为预览示意值。TODO-API: 用户列表接 admin 用户接口（G14）、角色接 roleApi.list。
 */
import { useState } from 'react';

const CSS = `
.ad { height:100%; overflow:hidden; display:flex; background:var(--color-canvas); font-family:-apple-system,'PingFang SC',sans-serif; font-size:14px; color:#1E1B2E; }
.ad * { box-sizing:border-box; }
.K-main { flex:1; padding:0; display:flex; background:var(--color-canvas); }
.K-card { background:#fff; border-radius:13px; box-shadow:0 1px 3px rgba(42,38,64,.05); }
.K-pill { font-size:10px; border-radius:99px; padding:2px 10px; font-weight:700; display:inline-block; }
.K-pg { background:#E8F6EE; color:#1F8A55; } .K-pr { background:#EFEAFD; color:#6D4AE0; }
.K-pw { background:#FDF3E1; color:#B97A0F; } .K-pe { background:#FEE2E2; color:#DC2626; }
.K-pd { background:#F1EFF8; color:#8A85A3; }
.K-bp { background:linear-gradient(135deg,#8B5CF6,#6D4AE0); color:#fff; border-radius:8px; padding:6px 18px; font-size:12px; font-weight:700; display:inline-block; cursor:pointer; }
.K-tbl { width:100%; border-collapse:collapse; font-size:13px; }
.K-tbl th { text-align:left; font-size:11px; color:#9A95B0; text-transform:uppercase; letter-spacing:.4px; padding:8px 10px; border-bottom:1px solid #EFEDF7; }
.K-tbl td { padding:9px 10px; border-bottom:1px solid #F4F2FA; color:#55506E; }
.K-tbl tr:last-child td { border-bottom:none; }
.an { padding:8px 12px; border-radius:8px; font-size:12.5px; color:#8A85A3; cursor:pointer; }
.an.on { background:#EFEAFD; color:#6D4AE0; font-weight:700; }
`;

const USERS = [
  { name: 'Logan Hu', role: 'admin', roleCls: 'K-pr', roleName: '超级管理员', perms: '全部 14 域', last: '刚刚' },
  { name: '陈数据', role: 'developer', roleCls: 'K-pg', roleName: '开发者', perms: 'agent · workflow · channel', last: '2 小时前' },
  { name: '王运营', role: 'operator', roleCls: 'K-pd', roleName: '运营', perms: 'session · knowledge · task', last: '昨天' },
];

const NAV = [
  { icon: '👥', label: '用户权限' },
  { icon: '🔌', label: '模型配置' },
  { icon: '⚙', label: '系统设置' },
  { icon: '↔', label: '导入导出' },
];

export function AdminPage() {
  const [nav, setNav] = useState('用户权限');

  return (
    <div className="ad">
      <style>{CSS}</style>
      <div className="K-main">
        {/* 子导航 */}
        <div style={{ width: 156, background: '#FBFAFE', borderRight: '1px solid #EFEDF7', padding: '14px 11px', display: 'flex', flexDirection: 'column', gap: 2, flex: 'none' }}>
          <div style={{ fontSize: 10, color: '#B6B1C9', fontWeight: 700, padding: '0 10px 6px' }}>管理</div>
          {NAV.map((n) => (
            <div key={n.label} className={`an ${nav === n.label ? 'on' : ''}`} onClick={() => setNav(n.label)}>
              {n.icon} {n.label}
            </div>
          ))}
        </div>
        {/* 内容区 */}
        <div style={{ flex: 1, padding: '17px 22px', overflowY: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
            <b style={{ fontSize: 16, fontWeight: 800 }}>{nav}</b>
            <span className="K-bp" style={{ marginLeft: 'auto' }}>＋ 邀请用户</span>
          </div>

          {nav === '用户权限' && (
            <>
              <div className="K-card" style={{ overflow: 'hidden' }}>
                <table className="K-tbl">
                  <thead><tr>{['用户', '角色', '权限域', '最近活跃', ''].map((h) => <th key={h}>{h}</th>)}</tr></thead>
                  <tbody>
                    {USERS.map((u) => (
                      <tr key={u.name}>
                        <td><b style={{ color: '#2A2640' }}>{u.name}</b> <span className={`K-pill ${u.roleCls}`}>{u.role}</span></td>
                        <td>{u.roleName}</td>
                        <td style={{ fontSize: 11, color: '#9A95B0' }}>{u.perms}</td>
                        <td>{u.last}</td>
                        <td style={{ color: '#6D4AE0', cursor: 'pointer' }}>编辑</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p style={{ fontSize: 11.5, color: '#9A95B0', margin: '11px 0 0' }}>
                权限域 pill 化（permission 数组直接映射为标签）；普通用户进入管理区只见「个人设置」。
              </p>
            </>
          )}
          {nav === '模型配置' && (
            <div className="K-card" style={{ padding: '60px 20px', textAlign: 'center', color: '#9A95B0', fontSize: 13 }}>
              渠道卡（供应商/密钥态/熔断状态灯/按码分级）+ 模型-渠道路由 — P4.5 接 modelApi
            </div>
          )}
          {nav === '系统设置' && (
            <div className="K-card" style={{ padding: '60px 20px', textAlign: 'center', color: '#9A95B0', fontSize: 13 }}>
              语音 / 通用 / 消息渠道 Tab（复用现有权限域门控）— P4.5
            </div>
          )}
          {nav === '导入导出' && (
            <div className="K-card" style={{ padding: '60px 20px', textAlign: 'center', color: '#9A95B0', fontSize: 13 }}>
              afpkg 资源包双向迁移 — P4.5 接 transfer-api
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
