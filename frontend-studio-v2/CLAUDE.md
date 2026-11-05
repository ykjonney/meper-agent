# frontend-studio-v2 开发约定

## 视觉自查清单（每次 UI 变更后必须核对）
1. 图标语义：**可点击展开的图标（ChevronDown/Right）永远是裸的灰色小箭头**；
   类别/功能图标一律带色框（`af-cat af-cat-*` 20px 圆角块）— 两者不得混淆
2. 宽度对齐：消息列与 Composer 统一 `px-5 + max-w-[820px] mx-auto`；
   正文/中间文本/活动卡全部 `w-full`
3. 执行活动卡默认收起；展开态 = 白卡 + 淡紫卡头 + 时序叙事流
4. 所有颜色来自 `src/index.css` token，禁止硬编码 hex
5. 失败态永不折叠：错误描述内联红显
