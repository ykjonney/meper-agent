"""Mock MCP 服务 — client 自助授权 E2E 测试用（挂在演示应用下）。

可起两个实例，分别挂到两个演示应用下（连接名区分，工具集不同——
不同工具让 LLM 的调用意图可区分，跨应用授权测试的关键）：

- 实例 A（默认）:  ``uv run python scripts/mock_mcp.py``
  → :9102，name=e2e-demo-mcp，工具 query_order（挂「演示应用（E2E）」）
- 实例 B:         ``uv run python scripts/mock_mcp.py --port 9103 --name e2e-demo-mcp-b --tools inventory``
  → :9103，name=e2e-demo-mcp-b，工具 query_inventory（挂「演示应用 B」）

调用链验证点：平台 MCP 拦截器会把用户对该应用授权的 session 注入
``Authorization: Bearer sess-xxx``（uvicorn 访问日志可见）；未授权/
凭证失效时请求到不了这里——平台在兑换阶段就返回了带标记的错误结果。
"""
from __future__ import annotations

import argparse

import uvicorn
from mcp.server.fastmcp import FastMCP


def build_server(name: str, tools: list[str]) -> FastMCP:
    mcp = FastMCP(name, host="127.0.0.1")

    if "order" in tools:

        @mcp.tool()
        def query_order(order_id: str) -> str:
            """查询订单状态（演示应用 A 的资源）。

            Args:
                order_id: 订单号，如 ORD-1001
            """
            return f"订单 {order_id}：已发货（mock 数据）"

    if "inventory" in tools:

        @mcp.tool()
        def query_inventory(sku: str) -> str:
            """查询仓库库存（演示应用 B 的资源，跨应用授权测试用）。

            Args:
                sku: 商品编码，如 SKU-2001
            """
            return f"商品 {sku}：库存 42 件（mock 数据，来自演示应用 B）"

    if "whoami" in tools:

        @mcp.tool()
        def who_am_i() -> str:
            """返回调用者身份（演示 per-user 凭证注入效果）。"""
            return "当前以用户授权的 session 调用（详见服务端日志 Authorization 头）"

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9102)
    parser.add_argument("--name", default="e2e-demo-mcp")
    parser.add_argument(
        "--tools",
        default="order,whoami",
        help="逗号分隔：order/inventory/whoami",
    )
    args = parser.parse_args()

    mcp = build_server(args.name, args.tools.split(","))
    # streamable-http 模式，路径 /mcp（与平台 mcp_connections.url 约定一致）
    uvicorn.run(
        mcp.streamable_http_app(),
        host="127.0.0.1",
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
