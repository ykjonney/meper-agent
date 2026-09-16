"""从 code 工具源码静态推导 output_schema（返回结构声明）。

工作流下游以 ``{{node.result.字段}}`` 引用工具输出——字段声明此前需手工
维护，而返回形态其实写在代码里：入口函数的 ``return {...}``` 字面量键与
值类型即可尽力推导（AST 静态分析，不执行代码、零运行时成本）。

口径（create / update / AI 生成草稿三处一致）：
- 用户**手工声明的字段优先**（output_schema.fields 非空不覆盖）
- 为空时按代码推导；无法推导（返回标量 / 动态构造）返回 {}
"""
from __future__ import annotations

import ast
from typing import Any

# 构造调用名 → schema 类型（len({})/dict()/str() 等常见形态）
_CALL_TYPE_MAP = {
    "str": "string", "int": "number", "float": "number", "bool": "boolean",
    "dict": "object",
}


def derive_output_schema(code: str, tool_name: str) -> dict[str, Any]:
    """入口函数（run 或与工具同名，含 -/_ 变体）的 dict 返回 → output_schema。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}

    names = {"run", tool_name, tool_name.replace("-", "_").replace("/", "_")}
    func = next(
        (
            n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names
        ),
        None,
    )
    if func is None:
        return {}

    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    # ast.walk 是 BFS——先按源码行号排序，保证多 return 按书写顺序合并
    returns = sorted(
        (n for n in ast.walk(func) if isinstance(n, ast.Return)),
        key=lambda n: getattr(n, "lineno", 0),
    )
    for node in returns:
        for f in _dict_fields(node.value):
            if f["name"] not in seen:  # 多个 return 合并，重名保首个
                seen.add(f["name"])
                fields.append(f)
    if not fields:
        return {}
    return {"type": "object", "fields": fields}


def _dict_fields(value: ast.expr | None) -> list[dict[str, Any]]:
    """dict 字面量 → [{name, type, is_list, fields?, description}]；非 dict 为空。"""
    if not isinstance(value, ast.Dict):
        return []
    out: list[dict[str, Any]] = []
    for k, v in zip(value.keys, value.values, strict=True):
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            continue  # **展开 / 非常量键——跳过
        out.append({"name": k.value, "description": "", **_infer_type(v)})
    return out


def _infer_type(v: ast.expr) -> dict[str, Any]:
    """字面量/构造调用 → 字段类型（尽力而为，未知按 string）。"""
    if isinstance(v, ast.Constant):
        if isinstance(v.value, bool):  # bool 是 int 子类——先判 bool
            return {"type": "boolean", "is_list": False}
        if isinstance(v.value, (int, float)):
            return {"type": "number", "is_list": False}
        return {"type": "string", "is_list": False}
    if isinstance(v, ast.List):
        if not v.elts:
            return {"type": "string", "is_list": True}
        return {**_infer_type(v.elts[0]), "is_list": True}
    if isinstance(v, ast.Dict):
        return {"type": "object", "is_list": False, "fields": _dict_fields(v)}
    if isinstance(v, ast.Compare):
        return {"type": "boolean", "is_list": False}  # 比较表达式恒为布尔
    if isinstance(v, ast.Call):
        fname = getattr(v.func, "id", "") or getattr(v.func, "attr", "")
        schema_type = _CALL_TYPE_MAP.get(fname)
        if schema_type:
            return {"type": schema_type, "is_list": False}
        if fname == "list":
            return {"type": "string", "is_list": True}
    return {"type": "string", "is_list": False}
