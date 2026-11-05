/**
 * 文本「字数」统计与截断 —— 中文“字数”口径（Word/WPS 同款）。
 *
 * CJK 字符（含中文标点）每字计 1，连续的非 CJK 非空白串（英文单词、
 * 数字、emoji 等）整体计 1，空白不计。思考内容、工具结果多为英文或
 * JSON，逐字符计数会数倍虚高于视觉感知，故展示统一走本口径。
 *
 * 思考过程卡片、工具结果折叠（ChatHomepage）与任务详情长文本
 * （DataView）共用，避免多处私有副本漂移。
 */

const CJK_RE = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u30ff\uff00-\uffef]/;

/** 按「字数」口径统计：CJK 每字 1；连续非 CJK 非空白串整体 1；空白不计。 */
export function countZi(s: string): number {
  let n = 0;
  let inRun = false;
  for (const ch of s) {
    if (CJK_RE.test(ch)) {
      n += 1;
      inRun = false;
    } else if (/\s/.test(ch)) {
      inRun = false;
    } else if (!inRun) {
      n += 1;
      inRun = true;
    }
  }
  return n;
}

/** 按「字数」口径截断：保留前 maxZi 个字对应的原文切片。计数与 countZi
 *  完全一致（游标推进，不经字符值反查）；使计数超出 maxZi 的字（run 的
 *  首字符）连同其后续内容一并切掉，前 maxZi 个字完整保留。 */
export function truncateByZi(s: string, maxZi: number): string {
  let n = 0;
  let inRun = false;
  let idx = 0; // 当前码点在原字符串中的起始位置（码点级遍历 + UTF-16 游标）
  for (const ch of s) {
    if (CJK_RE.test(ch)) {
      n += 1;
      inRun = false;
    } else if (/\s/.test(ch)) {
      inRun = false;
    } else if (!inRun) {
      n += 1;
      inRun = true;
    }
    if (n > maxZi) {
      return s.slice(0, idx);
    }
    idx += ch.length;
  }
  return s;
}
