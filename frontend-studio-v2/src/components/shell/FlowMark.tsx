/**
 * FlowMark — 产品标志：DAG 三节点流向图形（Agent Flow 的「流」抽象）。
 * 替代 AI 产品烂大街的 ✦ 星形。白色单色，用在品牌底色上。
 */
export function FlowMark({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      {/* 上节点 → 右节点 */}
      <circle cx="5.5" cy="6" r="2.2" fill="currentColor" stroke="none" />
      <circle cx="18.5" cy="12" r="2.2" fill="currentColor" stroke="none" />
      <circle cx="5.5" cy="18" r="2.2" fill="currentColor" stroke="none" />
      <path d="M7.6 7.1 L16.1 11.1 M7.6 16.9 L16.1 12.9" />
    </svg>
  );
}
