#!/usr/bin/env python3
"""Cython 编译构建器：app/ + agent_flow_harness/ → .so 产物树。

由 build_compiled.sh 在目标平台容器内调用；也可在本机直接跑（产出仅限
本机平台/arch）。产物目录结构与源码树同构，.py 全部替换为同名 .so，
非 .py 数据文件原样拷贝。

用法：
    python scripts/build_compiled.py --out dist/compiled [--release]

--release：正式构建标记（LICENSE_ENFORCED=True 编入 .so）；缺省 dev 构建
（LICENSE_ENFORCED=True + 公钥），产出"发布构建"；缺省产出 dev 构建
（不强制 license，供内部排障）。
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
from pathlib import Path

# 不编译的模块（保持 .py 源码随产物分发）：
# - app/cli/**：runpy（python -m app.cli）无法执行 __main__.so；且 CLI 是
#   纯 argparse dispatcher，无业务 IP。
# - app/_cycompat.py：Cython 兼容补丁必须在 .so 世界之前以源码运行。
# - **/tests/**：不需要进产物。
EXCLUDE_PARTS = {"cli", "tests"}
EXCLUDE_FILES = {"setup.py", "conftest.py", "_cycompat.py"}

# ── docstring 剥离：编译前 AST 移除全部 docstring（模块/类/函数）────────
# docstring 是给人看的，却是 .so 里最大的明文泄露源（含安全模块的设计自述）。
# 剥离后 ast.unparse 重写源码——注释/格式会丢，编译产物不在乎；语义不变。

class _DocStripper(ast.NodeTransformer):
    def _strip(self, node):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            if len(node.body) == 1:
                node.body = [ast.Pass()]  # 只剩 docstring 的 body 补 pass
            else:
                del node.body[0]
        return node

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        return self._strip(node)

    def visit_AsyncFunctionDef(self, node):
        self.generic_visit(node)
        return self._strip(node)

    def visit_ClassDef(self, node):
        self.generic_visit(node)
        return self._strip(node)

    def visit_Module(self, node):
        self.generic_visit(node)
        return self._strip(node)


def strip_docstrings(py: Path) -> None:
    """仅对安全敏感模块剥离 docstring（这些模块的设计说明是逆向路标）。

    工具/业务模块的 docstring 不能删——LangChain 的 function calling
    依赖函数 docstring 作为工具 description（删了会报
    "Function must have a docstring if description not provided"）。
    """
    rel = py.name
    # 只剥离安全相关文件的 docstring
    if rel not in ("license.py", "license_mw.py", "build_flags.py"):
        return  # 其他模块保留 docstring
    tree = ast.parse(py.read_text(encoding="utf-8"))
    tree = _DocStripper().visit(tree)
    ast.fix_missing_locations(tree)
    py.write_text(ast.unparse(tree), encoding="utf-8")

# Cython 编译失败的个别模块可加到这里（正则，匹配相对路径）。
# 留在产物里将以 .py 源码存在（妥协项，需逐一记录原因）。
FORCE_KEEP_SOURCE: list[re.Pattern[str]] = []


def iter_py_files(root: Path):
    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        if any(part in EXCLUDE_PARTS for part in rel.parts):
            continue
        if rel.name in EXCLUDE_FILES:
            continue
        if any(rx.search(str(rel)) for rx in FORCE_KEEP_SOURCE):
            continue
        yield p


def copy_tree_filtered(src: Path, dst: Path) -> None:
    """拷贝源码树到产物目录（排除 __pycache__/tests/cli 的源保留待处理）。"""
    for p in src.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(src)
        if "__pycache__" in rel.parts:
            continue
        if any(part in {"tests"} for part in rel.parts):
            continue  # 测试不进产物
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)


def inject_build_flags(staging: Path, enforce: bool) -> None:
    """注入强制开关（公钥/密钥已在 license.py 内嵌，无需外部注入）。"""
    bf = staging / "app" / "core" / "build_flags.py"
    if enforce:
        bf.write_text(
            '''"""Build-time injected flags (compiled into the distributed artifact)."""

LICENSE_ENFORCED: bool = True
''',
            encoding="utf-8",
        )
    else:
        bf.write_text(
            '''"""Build-time injected flags (dev build — license NOT enforced)."""

LICENSE_ENFORCED: bool = False
''',
            encoding="utf-8",
        )
    print(f"[+] build_flags 注入: enforced={enforce}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="产物输出目录")
    parser.add_argument("--release", action="store_true", help="正式构建（license 强制）")
    parser.add_argument("--keep-pyc-fallback", action="store_true",
                        help="（保底回退）产物改为 .pyc 而非 .so")
    args = parser.parse_args()

    backend_root = Path(__file__).resolve().parent.parent
    app_src = backend_root / "app"
    harness_src = backend_root / "packages" / "harness" / "src" / "agent_flow_harness"
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    staging_app = out / "app"
    staging_harness = out / "agent_flow_harness"

    # 1) 拷贝（源 + 数据文件）
    copy_tree_filtered(app_src, staging_app)
    copy_tree_filtered(harness_src, staging_harness)
    inject_build_flags(out, args.release)

    # 2) 编译 or .pyc 回退
    keep_py: list[Path] = []
    if args.keep_pyc_fallback:
        for staging in (staging_app, staging_harness):
            keep_py.extend(iter_py_files(staging))

    if args.keep_pyc_fallback:
        import compileall

        for py in keep_py:
            compileall.compile_file(str(py), quiet=2)
            py.unlink()
        print("[!] .pyc 回退模式：产物为字节码（保护弱于 .so）")
    else:
        from Cython.Build import cythonize
        from setuptools import Extension, setup

        targets = [
            Extension(mod, [str(py)])
            for mod, py in _prepare_and_collect(staging_app, staging_harness)
        ]
        # build_ext --inplace 按扩展名的点分路径相对 CWD 落盘 → chdir 到
        # 产物根（staging 树与包布局同构：app/... 与 agent_flow_harness/...）。
        import os

        prev_cwd = os.getcwd()
        os.chdir(out)
        try:
            setup(
                name="agent-flow-compiled",
                ext_modules=cythonize(
                    targets,
                    compiler_directives={
                        "language_level": "3",
                        "binding": True,
                        # 关键：不把 Python 注解当 C 类型声明。默认 True 时
                        # ``x: str = Header(...)`` 会因默认值非 str 在模块
                        # init 即抛 "Expected str, got Header"（FastAPI 的
                        # Header/Query/Depends 默认值全中招）。
                        "annotation_typing": False,
                        # 关键：关闭类型推断。Cython 3.3 对部分调用表达式
                        # （如 ``Callable[[str], object] | None`` 形参签名）
                        # 推断时会触发编译器崩溃（infer_type: args=None）。
                        "infer_types": False,
                    },
                    nthreads=4,
                ),
                script_args=["build_ext", "--inplace"],
            )
        finally:
            os.chdir(prev_cwd)

        # 3) 删除已编译模块的 .py（cli/数据文件天然保留）
        removed = 0
        for staging in (staging_app, staging_harness):
            for py in iter_py_files(staging):
                if _find_so(py) is not None:
                    py.unlink()
                    removed += 1
        # 4) 清理构建中间产物（.c / build/ 目录不进安装包）
        for staging in (staging_app, staging_harness):
            for c in staging.rglob("*.c"):
                c.unlink()
        shutil.rmtree(out / "build", ignore_errors=True)
        # strip：去 C 层 local symbols（实测符号减半、体积-8%；Python 层字符串不受影响）
        import subprocess as _sp
        for so in [*staging_app.rglob("*.so"), *staging_harness.rglob("*.so")]:
            _sp.run(["strip", "-x", str(so)], check=False, capture_output=True)
        print(f"[+] 编译完成：{removed} 个模块 → .so；cli/ 与数据文件保留源码")

    # 4) 产物自检：无残留业务 .py（除白名单 cli/_cycompat）
    leftover = [
        str(p.relative_to(out))
        for p in staging_app.rglob("*.py")
        if "cli" not in p.relative_to(staging_app).parts
        and p.name != "_cycompat.py"
    ]
    leftover += [str(p.relative_to(out)) for p in staging_harness.rglob("*.py")]
    if leftover and not args.keep_pyc_fallback:
        print("[!] 以下 .py 未编译（对照 FORCE_KEEP_SOURCE 检查）：")
        for f in leftover:
            print(f"    {f}")
    print(f"[+] 产物目录: {out}")


def _prepare_and_collect(staging_app: Path, staging_harness: Path):
    # 编译前剥离 docstring（staging 是副本，源码不受影响）
    for staging in (staging_app, staging_harness):
        for py in iter_py_files(staging):
            strip_docstrings(py)
    return list(_collect_targets(staging_app, staging_harness))

def _collect_targets(staging_app: Path, staging_harness: Path):
    """产出 (完整点分模块名, staging 内 .py 路径) 列表。"""
    for staging, prefix in ((staging_app, "app"), (staging_harness, "agent_flow_harness")):
        for py in iter_py_files(staging):
            rel = py.relative_to(staging).with_suffix("")
            yield f"{prefix}.{'.'.join(rel.parts)}", py


def _find_so(py: Path) -> Path | None:
    """同名（任意平台后缀）.so 是否存在。"""
    for cand in py.parent.glob(f"{py.stem}.*.so"):
        return cand
    plain = py.with_suffix(".so")
    return plain if plain.exists() else None


if __name__ == "__main__":
    main()
