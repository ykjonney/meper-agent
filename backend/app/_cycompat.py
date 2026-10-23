"""Cython 编译兼容补丁（本模块永远以 .py 源码分发，不参与编译）。

问题：Cython 编译后的方法类型是 ``cython_function_or_method``，不是
``types.FunctionType``——pydantic v2 的 ``default_ignored_types()`` 只忽略
后者，于是编译产物里 pydantic 模型上的普通方法（如 ``model_post_init``）
被误判为"缺注解的字段"，类创建即抛 PydanticUserError。

方案：在**任何 pydantic 模型类被创建之前**，给 pydantic 的忽略类型表
追加 cyfunction 类型。类型样本取自 ``app.core.errors.AppError.__init__``
（该模块零第三方依赖、最早可用；源码运行时取到的是 FunctionType，补丁
等于无操作，天然幂等）。

接线：app/main.py、app/workers/celery_app.py、app/cli/__main__.py 的
**第一条 import**。见 backend/scripts/build_compiled.py 的 EXCLUDE_FILES。
"""

from __future__ import annotations

_installed = False


def install() -> None:
    """幂等安装（重复调用安全）。"""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        from pydantic._internal import _model_construction as mc
    except ImportError:  # pydantic 不在（不可能，防御）
        return

    from app.core.errors import AppError

    cyfunc_type = type(AppError.__init__)  # 源码运行=FunctionType（无操作）

    orig = mc.default_ignored_types

    def patched() -> tuple[type, ...]:
        return (*orig(), cyfunc_type)

    # pydantic 模块内部经全局名调用 default_ignored_types()，改模块属性即生效。
    mc.default_ignored_types = patched  # type: ignore[assignment]
