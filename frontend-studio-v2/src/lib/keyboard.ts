/** 键盘事件工具。 */

/** Enter 发送前置守卫：中文 IME 组合输入中（拼音选词/确认候选）的 Enter
 *  不是"发送"语义。判据两条缺一不可：
 *  - isComposing：标准组合输入标记（Chrome/Firefox 组合期间的 keydown 为 true）；
 *  - keyCode 229：Safari 的 compositionend 先于 keydown 派发，此时
 *    isComposing 已是 false，只能靠 229（IME 处理中）兜底。
 *  用法：onKeyDown 里最先调用，为 true 直接 return。 */
export function isImeComposing(e: {
  nativeEvent: KeyboardEvent;
  keyCode?: number;
}): boolean {
  return e.nativeEvent.isComposing || e.keyCode === 229;
}
