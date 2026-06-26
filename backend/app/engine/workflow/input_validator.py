"""Workflow 输入变量约束校验器。

校验 Start 节点的 output_variables 中各类型约束：
- required（所有类型）
- text: min_length / max_length
- number: min / max / precision
- json: schema（JSON Schema 校验）
- select: options（值必须在选项列表内）
- file: 委托给 file_validator（FileRef 存在性 / 扩展名 / 大小）

返回 (ok, error_message)。ok=True 表示通过。
"""
from __future__ import annotations

from typing import Any


def _is_empty(value: Any) -> bool:
    """判断值是否为「空」（用于 required 判断）。"""
    return value is None or value == "" or (isinstance(value, list) and len(value) == 0)


async def validate_input_variables(
    output_variables: list[dict[str, Any]],
    task_input: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """校验一组变量定义对应的输入值。

    Args:
        output_variables: Start 节点 config.output_variables 定义列表
        task_input: 用户传入的 input dict

    Returns:
        ``(resolved, error)`` — resolved 为处理后（含默认值、文件解析）的 dict；
        error 为 None 表示全部通过。
    """
    resolved: dict[str, Any] = {}
    missing: list[str] = []

    for var_def in output_variables:
        if not isinstance(var_def, dict):
            continue
        name = var_def.get("name", "")
        if not name:
            continue

        var_type = var_def.get("type", "text")
        constraints = (
            var_def["constraints"]
            if isinstance(var_def.get("constraints"), dict)
            else {}
        )
        is_required = bool(
            constraints.get("required", var_def.get("required"))
        )
        default_val = constraints.get("default_value", var_def.get("default"))

        # 取值优先级：task_input > default_value > None
        if name in task_input:
            value = task_input[name]
        elif default_val not in (None, ""):
            value = default_val
        else:
            value = None

        # ── required 检查 ──
        if is_required and _is_empty(value):
            label = var_def.get("label") or name
            display = f"{name}({label})" if label != name else name
            missing.append(display)
            continue

        # 空值且非必填：直接跳过后续约束校验
        if _is_empty(value):
            resolved[name] = value
            continue

        # ── file 类型：委托给 file_validator（异步） ──
        if var_type == "file":
            from app.engine.workflow.file_validator import validate_file_variable

            file_resolved, ferror = await validate_file_variable(value, var_def)
            if ferror:
                return {}, f"文件变量 '{name}' 验证失败: {ferror}"
            resolved[name] = file_resolved
            continue

        # ── 其它类型：同步约束校验 ──
        err = _validate_by_type(var_type, value, constraints)
        if err:
            return {}, f"变量 '{name}' 校验失败: {err}"

        resolved[name] = value

    if missing:
        return {}, f"必填输入字段缺失: {', '.join(missing)}"

    return resolved, None


def _validate_by_type(
    var_type: str,
    value: Any,
    constraints: dict[str, Any],
) -> str | None:
    """对单个非空值做类型相关约束校验。返回 None 或错误消息。"""

    if var_type == "text":
        return _validate_text(value, constraints)
    elif var_type == "number":
        return _validate_number(value, constraints)
    elif var_type == "json":
        return _validate_json(value, constraints)
    elif var_type == "select":
        return _validate_select(value, constraints)
    # file / boolean 不需要在这里校验（file 由 file_validator 异步处理，boolean 无约束）
    return None


def _validate_text(value: Any, constraints: dict[str, Any]) -> str | None:
    if not isinstance(value, str):
        return f"期望字符串，收到 {type(value).__name__}"
    min_len = constraints.get("min_length")
    max_len = constraints.get("max_length")
    if min_len is not None and len(value) < int(min_len):
        return f"长度 {len(value)} 小于最小长度 {int(min_len)}"
    if max_len is not None and len(value) > int(max_len):
        return f"长度 {len(value)} 超过最大长度 {int(max_len)}"
    return None


def _validate_number(value: Any, constraints: dict[str, Any]) -> str | None:
    if not isinstance(value, (int, float)):
        return f"期望数字，收到 {type(value).__name__}"
    min_val = constraints.get("min")
    max_val = constraints.get("max")
    precision = constraints.get("precision")
    if min_val is not None and value < min_val:
        return f"值 {value} 小于最小值 {min_val}"
    if max_val is not None and value > max_val:
        return f"值 {value} 超过最大值 {max_val}"
    if precision is not None and isinstance(value, float):
        decimals = len(str(value).rstrip("0").split(".")[-1]) if "." in str(value) else 0
        if decimals > int(precision):
            return f"小数位 {decimals} 超过精度限制 {int(precision)}"
    return None


def _validate_json(value: Any, constraints: dict[str, Any]) -> str | None:
    schema = constraints.get("schema")
    if not schema:
        return None
    try:
        import jsonschema
        jsonschema.validate(instance=value, schema=schema)
    except ImportError:
        # jsonschema 未安装时跳过 schema 校验
        return None
    except Exception as exc:
        return f"JSON Schema 校验失败: {exc.message}" if hasattr(exc, "message") else f"JSON Schema 校验失败: {exc}"
    return None


def _validate_select(value: Any, constraints: dict[str, Any]) -> str | None:
    options = constraints.get("options")
    if not options or not isinstance(options, list):
        return None
    multiple = bool(constraints.get("multiple", False))
    if multiple:
        if not isinstance(value, list):
            return f"多选期望列表，收到 {type(value).__name__}"
        invalid = [v for v in value if v not in options]
        if invalid:
            return f"值 {invalid} 不在选项列表内"
    else:
        if value not in options:
            return f"值 {value!r} 不在选项列表内"
    return None
