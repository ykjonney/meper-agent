"""resolve_variable — use 字符串动态加载工具（v0.2-x 第三层接入增强）。

支持 agent_doc["tools"] 里的 ``use: "模块路径:符号名"`` 格式，动态 import
目标对象并做类型校验。与 deer-flow resolve_variable 对齐。让宿主声明式
注入工具，免去手动 import + 实例化每个工具类。

向后兼容：无 use 字段的 tool entry 继续走 ToolRegistry 实例查找。
"""
from __future__ import annotations

import importlib
from typing import Any


def resolve_variable(use: str, expected_type: type) -> Any:
    """把 ``"模块路径:符号名"`` 解析为实际对象，并校验类型。

    Args:
        use: 形如 ``"agent_flow_harness.interaction:tool_search"`` 的路径。
            必须含且仅含一个冒号分隔模块与符号。
        expected_type: 期望的对象类型，不符则 raise TypeError。

    Returns:
        解析出的对象。

    Raises:
        ValueError: use 格式错误（无冒号）。
        ModuleNotFoundError: 模块无法导入。
        AttributeError: 符号在模块中不存在。
        TypeError: 对象类型与 expected_type 不符。
    """
    if ":" not in use:
        msg = (
            f"Invalid use path '{use}': expected format 'module.path:symbol'"
        )
        raise ValueError(msg)

    module_path, _, symbol = use.partition(":")
    if not module_path or not symbol:
        msg = f"Invalid use path '{use}': module and symbol must be non-empty"
        raise ValueError(msg)

    mod = importlib.import_module(module_path)
    obj = getattr(mod, symbol)

    if not isinstance(obj, expected_type):
        msg = (
            f"use '{use}' resolved to {type(obj).__name__}, "
            f"expected {expected_type.__name__}"
        )
        raise TypeError(msg)

    return obj


__all__ = ["resolve_variable"]
