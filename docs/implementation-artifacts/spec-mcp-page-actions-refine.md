---
title: 'MCP 页面操作按钮精简 + URL 视觉修复'
type: 'refactor'
created: '2026-06-10'
status: 'done'
route: 'one-shot'
---

## Intent

**Problem:** MCP 连接列表每行有「测试连接」和「发现工具」两个独立操作按钮，功能高度重叠（测试连接成功后也会返回工具数量），造成用户操作混淆；同时 URL 单元格的边框+背景色产生不必要的视觉阴影效果。

**Approach:** 将两个按钮合并为单一的「查看工具详情」操作（先测连接再发现工具，联动展示结果），简化 URL 单元格样式去掉边框和背景。

## Suggested Review Order

1. `frontend/src/pages/mcp-page.tsx:151` — `detailMutation` 定义：确认 test + discover 联动逻辑正确
2. `frontend/src/pages/mcp-page.tsx:255` — `handleViewDetail`：确认操作入口调用正确
3. `frontend/src/pages/mcp-page.tsx:397` — 操作按钮区：确认「查看工具详情」按钮替换了两个旧按钮
4. `frontend/src/pages/mcp-page.tsx:375` — URL 单元格：确认去掉了边框和背景
5. `frontend/src/pages/mcp-page.tsx:16-24` — Icon 导入：确认去掉了未使用的图标
