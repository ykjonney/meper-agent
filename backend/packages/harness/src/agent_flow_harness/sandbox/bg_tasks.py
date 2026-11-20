"""后台任务 shell 包装构建器 — bash(run_in_background)/bash_output 共用。

设计文档：docs/background-tasks.md。文件布局（bash cwd = 容器内
/workspace/tmp，即宿主工作区 tmp/，随工作区持久、跨 turn 可查）：

    tmp/.af_bg/
        {id}.cmd     用户命令脚本（含退出码落盘尾巴，纯文本）
        {id}.log     nohup 输出
        {id}.pid     容器内 pid
        {id}.start   启动时间（epoch 秒）
        {id}.exit    结束时写入退出码（存在 = finished）
        {id}.off     bash_output 已读字节偏移（增量读取）
        {id}.read    finished 后被 bash_output 读过一次的标记

安全：task_id 必须经 ``is_valid_task_id`` 校验（会被拼进 shell 命令）；
用户命令经 base64 编码传递，规避双层 shell 引号问题。
"""
from __future__ import annotations

import base64
import re
from uuid import uuid4

# 软超时：超过该秒数的运行中任务在 bash_output 调用时被 kill（对齐
# Claude Code 的 30min SIGTERM）。硬超时（beat 清扫）依赖沙盒环境方向
# 结论，暂缓——见 docs/background-tasks.md §5。
BG_TASK_MAX_LIFETIME = 1800
# 单次 bash_output 返回的新增输出字节上限
BG_OUTPUT_CAP = 16_000
_BG_ID_RE = re.compile(r"^bg-[0-9a-f]{6,12}$")


def is_valid_task_id(task_id: str) -> bool:
    """task_id 会被拼进 shell 命令，必须先校验（防注入）。"""
    return bool(_BG_ID_RE.match(task_id))


def new_task_id() -> str:
    return f"bg-{uuid4().hex[:6]}"


def build_start_exec(task_id: str, command: str) -> str:
    """构造启动后台任务的 exec 命令（毫秒级返回，不等待任务）。

    用户命令经 base64 落为 {id}.cmd，尾部注入退出码落盘——finished
    判定与 exit code 的来源。
    """
    inner = command + f'\nprintf %s "$?" > .af_bg/{task_id}.exit\n'
    b64 = base64.b64encode(inner.encode("utf-8")).decode("ascii")
    d = f".af_bg/{task_id}"
    return "\n".join([
        "mkdir -p .af_bg",
        f"printf '%s' '{b64}' | base64 -d > {d}.cmd",
        "date +%s > " + f"{d}.start",
        f"nohup bash {d}.cmd > {d}.log 2>&1 &",
        f"echo $! > {d}.pid",
        f'echo "started background task {task_id} (pid $(cat {d}.pid))"',
    ])


def build_output_exec(
    task_id: str,
    *,
    block_timeout: int = 0,
    max_lifetime: int | None = None,
    cap: int | None = None,
) -> str:
    # 默认值运行时取（而非定义时绑定）——测试可 monkeypatch 常量
    max_lifetime = BG_TASK_MAX_LIFETIME if max_lifetime is None else max_lifetime
    cap = BG_OUTPUT_CAP if cap is None else cap
    """构造 bash_output 的 exec 命令：探活 + 增量读取 + 软超时。

    block_timeout>0 时在 exec 内轮询等待任务结束（分段等待模式），
    期间同样执行软超时检查。返回首行 ``__AF_BG__status=... ...`` 状态
    行，其后为新增输出。
    """
    d = f".af_bg/{task_id}"
    lines = [
        f"d={d}",
        "if [ ! -f $d.pid ]; then echo '__AF_BG__status=unknown'; exit 0; fi",
        "pid=$(cat $d.pid)",
        "start=$(cat $d.start 2>/dev/null || echo 0)",
        "now=$(date +%s); age=$((now - start))",
        "st=running; ex=''",
        "if [ -f $d.exit ]; then st=finished; ex=$(cat $d.exit); fi",
        f"if [ $st = running ] && [ $age -ge {max_lifetime} ]; then "
        f"kill $pid 2>/dev/null; st=timeout; fi",
    ]
    if block_timeout > 0:
        lines += [
            f"deadline=$((now + {int(block_timeout)}))",
            "while [ ! -f $d.exit ] && [ $st != timeout ] "
            "&& [ $(date +%s) -lt $deadline ]; do "
            "sleep 2; "
            "now=$(date +%s); age=$((now - start)); "
            f"if [ $age -ge {max_lifetime} ]; then kill $pid 2>/dev/null; "
            "st=timeout; break; fi; "
            "done",
            "if [ -f $d.exit ]; then st=finished; ex=$(cat $d.exit); fi",
        ]
    lines += [
        "off=$(cat $d.off 2>/dev/null || echo 0)",
        # BSD wc 输出带前导空格，算术归一化
        "total=$(wc -c < $d.log 2>/dev/null || echo 0); total=$((total + 0))",
        "printf '%s' \"$total\" > $d.off",
        "echo \"__AF_BG__status=$st exit=$ex age=$age total=$total\"",
        f"tail -c +$((off + 1)) $d.log 2>/dev/null | head -c {cap}",
        "if [ $st != running ]; then printf %s 1 > $d.read; fi",
    ]
    return "\n".join(lines)


_BG_STATUS_RE = re.compile(r"__AF_BG__status=(\w+)(?: exit=(\S+))?(?: age=(\d+))?(?: total=(\d+))?")


def parse_output_exec(stdout: str) -> tuple[dict[str, str], str]:
    """解析 bash_output exec 结果 → (状态字典, 新增输出文本)。

    无状态行（exec 失败/超时截断）时返回 ({}, 原样 stdout)。
    """
    m = _BG_STATUS_RE.search(stdout)
    if m is None:
        return {}, stdout
    status = {
        "status": m.group(1),
        "exit": m.group(2) or "",
        "age": m.group(3) or "0",
        "total": m.group(4) or "0",
    }
    output = stdout[m.end():]
    # 状态行后紧跟的换行属于分隔，不属输出
    if output.startswith("\n"):
        output = output[1:]
    return status, output


__all__ = [
    "BG_OUTPUT_CAP",
    "BG_TASK_MAX_LIFETIME",
    "build_output_exec",
    "build_start_exec",
    "is_valid_task_id",
    "new_task_id",
    "parse_output_exec",
]
