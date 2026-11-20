"""bash cwd 持久 — Claude Code 同款的"追踪-重放"机制。

每次 execute_command 是一个一次性 shell 进程，cd 的效果随进程死亡。
本模块用两条包装让 cwd 跨调用持久（对齐 Claude Code 的反向工程实现）：

- 注入：命令前 ``cd '<上次 cwd>'``，失败静默退回默认目录（目录可能
  已被删除）；
- 捕获：命令结束后向 stdout 追加 ``<marker><PWD>``，调用方解析出
  新 cwd 存回实例状态，并把 marker 段从 stdout 中剥离。

env 不持久（Claude Code 同语义，官方文档明确）——export 需在同一条
命令内完成。并发语义：并行调用各自从同一 cwd 出发，捕获取最后完成
者（依赖 cwd 的操作请勿并行，文档由工具描述告知）。

marker 用随机 token 防命令自身输出碰撞；解析不到 marker（超时/命令
内 exit/异常）时保持原 cwd 不变。
"""
from __future__ import annotations

import re
from uuid import uuid4


def _quote(path: str) -> str:
    """单引号安全转义（POSIX shell）。"""
    return "'" + path.replace("'", "'\\''") + "'"


def wrap_cwd_command(command: str, cwd: str) -> tuple[str, "re.Pattern[str]"]:
    """包装命令：注入 cd + 捕获 PWD。返回 (wrapped, marker 解析正则)。"""
    token = uuid4().hex[:12]
    marker = f"__AF_PWD_{token}__"
    wrapped = (
        f"cd {_quote(cwd)} >/dev/null 2>&1 || true\n"
        f"{{ {command}\n}}\n"
        f"__af_rc=$?\n"
        f"printf '%s' '{marker}'\"$PWD\"\n"
        f"exit $__af_rc"
    )
    # DOTALL：命令输出可能多行；非贪婪截取 marker 后到串尾的 $PWD
    parse_re = re.compile(rf"(?s)(.*?)({marker}(.*))$", re.DOTALL)
    return wrapped, parse_re


def extract_cwd(stdout: str, parse_re: "re.Pattern[str]") -> tuple[str, str]:
    """从 stdout 解析 (新 stdout, 新 cwd)；无 marker 时 cwd 返回空串。"""
    m = parse_re.search(stdout)
    if m is None:
        return stdout, ""
    body, _marker_and_pwd, pwd = m.group(1), m.group(2), m.group(3)
    # marker 前若紧贴命令输出的换行被 printf 顶掉——去掉一个结尾换行
    if body.endswith("\n"):
        body = body[:-1]
    return body, pwd


__all__ = ["extract_cwd", "wrap_cwd_command"]
