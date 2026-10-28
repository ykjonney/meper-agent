"""DockerSandbox — Docker 容器沙箱实现（比 LocalSandbox 隔离更强）。

从 backend 的 SandboxExecutor 提取，去掉了 ``app.*`` 依赖，配置通过
DockerSandboxConfig 注入。降级策略 fail-closed：沙箱禁用或 Docker 不可用
时默认**拒绝**执行，仅当 ``allow_local_fallback=True``（显式开发选项）才
降级到本机 subprocess，且每次降级打 ERROR 日志。

安全特性：
- 容器只读根文件系统 + no-new-privileges
- 网络禁用（network_mode="none"）
- 内存/CPU 限制
- tmpfs for /tmp
- 非 root 用户执行

运行时治理：
- docker client 进程级复用（_get_docker_client，每命令省 from_env+ping）
- max_concurrent>0 时进程级信号量限并发（含 subprocess 降级路径）
- 容器打 agent-flow.* label，供外部孤儿清扫任务识别遗留容器
- stdout/stderr 分流回收

用法：
    config = DockerSandboxConfig(image="agent-sandbox:latest", enabled=True)
    sandbox = DockerSandbox(sandbox_id="s1", work_dir=Path("/workspace"),
                            mounts={"tmp": Path("/workspace/tmp")}, config=config)
    result = sandbox.execute_command("ls -la")
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import structlog

from agent_flow_harness.sandbox.base import GrepMatch, Sandbox, SandboxResult
from agent_flow_harness.sandbox.edit_ops import apply_edits
from agent_flow_harness.sandbox.file_lock import file_mutation_lock

logger = structlog.get_logger(__name__)


# ── 进程级共享资源（docker client / 并发信号量）────────────────────────
# DockerSandbox 每次执行装配都新建实例，但 client 与并发上限是进程级概念，
# 必须放模块级单例，否则复用/限流失效。

_docker_client: Any = None
_client_lock = threading.Lock()


def _get_docker_client() -> Any:
    """进程级复用 docker client（每命令 from_env+ping 有百毫秒级开销）。

    失败时清空缓存，下次调用重试（daemon 可能恢复）。线程安全性由
    docker-py 内部的 urllib3 连接池保证。
    """
    global _docker_client
    if _docker_client is not None:
        return _docker_client
    with _client_lock:
        if _docker_client is not None:
            return _docker_client
        try:
            import docker  # type: ignore[import-untyped]
        except ImportError as exc:
            raise _DockerUnavailableError("docker package not installed") from exc
        try:
            client = docker.from_env(timeout=30)
            client.ping()
        except Exception as exc:
            raise _DockerUnavailableError(str(exc)) from exc
        _docker_client = client
        return client


def _reset_docker_client() -> None:
    """清空 client 缓存（测试用；daemon 重启后请求失败会自然重建）。"""
    global _docker_client
    with _client_lock:
        _docker_client = None


_semaphore: threading.BoundedSemaphore | None = None
_semaphore_limit = 0
_semaphore_lock = threading.Lock()


def _get_semaphore(limit: int) -> threading.BoundedSemaphore:
    """按 limit 取进程级并发信号量（limit 变化时重建——仅测试场景）。"""
    global _semaphore, _semaphore_limit
    with _semaphore_lock:
        if _semaphore is None or _semaphore_limit != limit:
            _semaphore = threading.BoundedSemaphore(limit)
            _semaphore_limit = limit
        return _semaphore


# ── 复用模式：进程级常驻容器注册表 ──────────────────────────────────────
# 每工作区长驻容器（docker exec 执行命令），省每命令容器冷启动。容器键 =
# (image, network_mode, mounts)，确定性命名 → 跨进程重启可按名收养。
# 工作区天然按用户划分，故多用户绝不共容器。

# 容器内 last-used 时间戳文件（tmpfs）。docker label 不可变，只能落容器内；
# beat 闲置回收任务 exec 读它判断驻留。app 侧共用本常量。
SANDBOX_LAST_USED_FILE = "/tmp/.agent-flow-last-used"

_CONTAINERS_PREFIX = "agent-flow-sbx-"


class _RegistryEntry:
    """注册表条目：容器对象 + LRU 时间戳 + exec 占用计数。"""

    __slots__ = ("container", "last_used", "busy")

    def __init__(self, container: Any) -> None:
        self.container = container
        self.last_used = time.monotonic()
        self.busy = 0


_containers: dict[str, _RegistryEntry] = {}
_registry_lock = threading.Lock()


def sandbox_container_name(
    mounts: dict[str, Path] | None, image: str, network_mode: str
) -> str:
    """确定性容器名：同键必同名（复用查找与跨进程收养的依据）。"""
    key = "|".join(
        [
            image,
            network_mode,
            *[f"{n}:{Path(p).resolve()}" for n, p in sorted((mounts or {}).items())],
        ]
    )
    return _CONTAINERS_PREFIX + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def remove_sandbox_container(name: str) -> bool:
    """按名移除复用容器（幂等）。app 在 session/task 删除时调用。

    先查进程注册表，未命中（跨进程/已重启）直接找 daemon。
    """
    with _registry_lock:
        entry = _containers.pop(name, None)
    removed = False
    if entry is not None:
        with contextlib.suppress(Exception):
            entry.container.remove(force=True)
            removed = True
    try:
        _get_docker_client().containers.get(name).remove(force=True)
        removed = True
    except Exception:
        pass
    return removed


def _evict_locked() -> None:
    """LRU 驱逐（调用方持 _registry_lock）：删最久未用的空闲容器直至有余量。

    全部 busy 时提前返回——上层约束 max_containers > max_concurrent 保证
    不会发生（信号量限制同时在执行的命令数 < 容器上限）。
    """
    # 注意：调用方传入 limit 之前已判断；此处直接读 dict 长度由调用方循环控制
    candidates = [(n, e) for n, e in _containers.items() if e.busy == 0]
    if not candidates:
        return
    name, entry = min(candidates, key=lambda kv: kv[1].last_used)
    del _containers[name]
    with contextlib.suppress(Exception):
        entry.container.remove(force=True)
    logger.info("sandbox_container_evicted", container=name)


def _is_within(path: Path, base: Path) -> bool:
    """path 是否位于 base 目录树内。"""
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


class DockerSandboxConfig:
    """Docker 沙箱配置（从 backend settings 提取，去 app.* 依赖）。

    所有字段有合理默认值，用户按需覆盖。
    """

    def __init__(
        self,
        *,
        image: str = "agent-sandbox:latest",
        enabled: bool = False,
        mem_limit: str = "512m",
        cpu_quota: int = 100_000,
        timeout: int = 120,
        max_output_bytes: int = 1_000_000,
        network_mode: str = "none",
        container_workspace_dir: str = "/workspace",
        container_skills_dir: str = "/skills",
        allow_local_fallback: bool = False,
        bind_source_mapper: Callable[[str], str] | None = None,
        max_concurrent: int = 0,
        reuse_container: bool = False,
        max_containers: int = 0,
    ) -> None:
        self.image = image
        self.enabled = enabled
        self.mem_limit = mem_limit
        self.cpu_quota = cpu_quota
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes
        self.network_mode = network_mode
        self.container_workspace_dir = container_workspace_dir
        self.container_skills_dir = container_skills_dir
        # Fail-closed 降级闸：False（默认）时沙箱不可用即拒绝执行；
        # True 时降级本机 subprocess（仅限开发环境），每次降级打 ERROR。
        self.allow_local_fallback = allow_local_fallback
        # Bind mount 源路径换算（backend 进程视角 → docker daemon 宿主视角）。
        # backend 容器化部署时进程看到 /data/workspaces，但沙箱容器由宿主
        # daemon 创建，volumes 源必须是 daemon 可见的宿主路径。仅作用于
        # docker run 的 volumes 源；read/write 等宿主侧文件操作仍用进程
        # 视角路径。默认 None = 同路径（本地开发）。
        self.bind_source_mapper = bind_source_mapper
        # 进程级最大并发容器数（含 subprocess 降级路径）。0 = 不限（默认，
        # 向后兼容）。按内存估算：每容器 mem_limit（默认 512m）→ 8 ≈ 4GB。
        # 注意 Celery prefork 每个并发槽位一个子进程，节点总上限 =
        # worker 并发数 × 本值。
        self.max_concurrent = max_concurrent
        # 复用模式：每工作区长驻容器，命令经 docker exec 执行（省每命令
        # 冷启动）。False = 旧行为（每命令一次性容器），一键回退。
        self.reuse_container = reuse_container
        # 进程内存活复用容器上限（LRU 驱逐最久未用；0 = 不限）。
        # 不变量：须大于 max_concurrent，保证超限时总有空闲容器可驱逐。
        self.max_containers = max_containers
        if (
            self.reuse_container
            and self.max_containers
            and self.max_concurrent
            and self.max_containers <= self.max_concurrent
        ):
            raise ValueError(
                "max_containers must exceed max_concurrent — LRU eviction "
                "needs an idle (not busy) container to evict at the cap"
            )


class _DockerUnavailableError(Exception):
    """Docker daemon 不可用或镜像缺失。"""


class DockerSandbox(Sandbox):
    """Docker 容器沙箱（强隔离），带显式开启的 subprocess fallback。

    execute_command 优先用 Docker（enabled=True 且 daemon 可达）；沙箱不可
    用时默认拒绝执行，仅 allow_local_fallback=True 时降级 subprocess（与
    LocalSandbox 相同，但每次降级打 ERROR 日志）。
    read_file/write_file/glob/grep 操作宿主机工作区目录（容器挂载的
    tmp/input/output），workspace 模式下三者均可达。
    """

    def __init__(
        self,
        sandbox_id: str,
        work_dir: Path,
        *,
        config: DockerSandboxConfig | None = None,
        mounts: dict[str, Path] | None = None,
        timeout: int = 120,
        max_output_chars: int = 50_000,
    ) -> None:
        self._id = sandbox_id
        self._work_dir = Path(work_dir).resolve()
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._config = config or DockerSandboxConfig()
        self._mounts = mounts or {"tmp": self._work_dir / "tmp"}
        self._timeout = timeout
        self._max_output = max_output_chars
        # input/output 宿主目录：优先取 mounts（app 场景恒传入），否则按
        # {root}/input、{root}/output 布局推导（与 _safe_resolve_output 一致）。
        self._output_dir = (
            Path(self._mounts["output"]).resolve()
            if "output" in self._mounts
            else self._work_dir.parent / "output"
        )
        self._input_dir = (
            Path(self._mounts["input"]).resolve()
            if "input" in self._mounts
            else self._work_dir.parent / "input"
        )
        # workspace 模式：work_dir 为 {root}/tmp 结构（app 场景恒成立）时，
        # 文件工具可访问整个工作区——tmp 工作区 / input 只读输入 / output 产物，
        # 各目录职能不同但 read/edit/glob/grep 均可操作；否则维持单 work_dir
        # 行为（独立使用场景）。
        self._workspace_mode = self._work_dir.name == "tmp"
        self._root = self._work_dir.parent if self._workspace_mode else self._work_dir

    @property
    def id(self) -> str:
        return self._id

    # ── 命令执行 ──────────────────────────────────────────────────────

    def execute_command(
        self,
        command: str,
        *,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """执行命令：Docker（enabled）；本机 subprocess 仅在显式允许时降级。

        env 为额外注入的环境变量（凭证等），容器/子进程内可见，宿主进程不受影响。
        配置了 max_concurrent>0 时，整条命令生命周期（含降级路径）受进程级
        信号量约束，超限排队等待。
        """
        effective_timeout = timeout if timeout is not None else self._timeout
        limit = self._config.max_concurrent
        if limit <= 0:
            return self._execute_dispatch(command, effective_timeout, env)
        semaphore = _get_semaphore(limit)
        queue_start = time.monotonic()
        semaphore.acquire()
        try:
            waited = time.monotonic() - queue_start
            if waited >= 0.1:
                logger.info(
                    "sandbox_queue_wait",
                    sandbox_id=self._id,
                    waited_ms=round(waited * 1000),
                    limit=limit,
                )
            return self._execute_dispatch(command, effective_timeout, env)
        finally:
            semaphore.release()

    def _execute_dispatch(
        self, command: str, effective_timeout: int, env: dict[str, str] | None
    ) -> SandboxResult:
        """选择执行通道：禁用/不可用时走 fail-closed 降级闸；复用模式走
        常驻容器 exec，否则每命令一次性容器。"""
        if not self._config.enabled:
            return self._fallback_or_refuse(
                command, effective_timeout,
                reason="sandbox disabled (enabled=False)",
                env=env,
            )

        try:
            if self._config.reuse_container:
                return self._execute_docker_reused(command, effective_timeout, env)
            return self._execute_docker(command, effective_timeout, env)
        except _DockerUnavailableError as exc:
            return self._fallback_or_refuse(
                command, effective_timeout,
                reason=f"docker unavailable ({exc})",
                env=env,
            )
        except Exception as exc:
            return SandboxResult(
                stdout="",
                stderr=f"Sandbox execution error: {exc}",
                exit_code=1,
            )

    def _fallback_or_refuse(
        self, command: str, timeout: int, *, reason: str,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Fail-closed 降级闸。

        默认（allow_local_fallback=False）拒绝执行并返回可操作的错误信息；
        显式开启后降级到本机 subprocess 并打 ERROR 日志——LLM 生成的命令
        正在无隔离地跑在宿主机上，这必须可见、可告警。
        """
        if not self._config.allow_local_fallback:
            return SandboxResult(
                stdout="",
                stderr=(
                    f"Sandbox unavailable and local fallback is not allowed: {reason}. "
                    "Set allow_local_fallback=True (SANDBOX_FALLBACK=local in the app) "
                    "to permit host execution — development only."
                ),
                exit_code=1,
            )
        logger.error(
            "sandbox_local_fallback",
            reason=reason,
            command_preview=command[:200],
            hint="LLM-generated command executing on host without isolation",
        )
        return self._execute_subprocess(command, timeout, env=env)

    def _build_volumes(self) -> dict[str, dict[str, str]]:
        """构建 docker run 的 volumes 映射（bind mount 源 → 容器挂载点）。

        input 名约定 ro、其余 rw；源路径经 bind_source_mapper（若配置）
        从 backend 进程视角换算为 daemon 宿主视角。
        """
        ws_dir = self._config.container_workspace_dir
        volumes: dict[str, dict[str, str]] = {}
        for name, host_path in self._mounts.items():
            mode = "ro" if name == "input" else "rw"
            source = str(Path(host_path).resolve())
            if self._config.bind_source_mapper:
                source = self._config.bind_source_mapper(source)
            volumes[source] = {
                "bind": f"{ws_dir}/{name}",
                "mode": mode,
            }
        return volumes

    def _execute_docker(
        self, command: str, timeout: int, env: dict[str, str] | None = None
    ) -> SandboxResult:
        """Docker 容器内执行（从 backend SandboxExecutor 提取）。"""
        client = _get_docker_client()

        volumes = self._build_volumes()

        env = {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            **(env or {}),
        }
        start = time.monotonic()
        timed_out = False

        try:
            container = client.containers.run(
                image=self._config.image,
                command=["bash", "-c", command],
                volumes=volumes,
                environment=env,
                working_dir=f"{self._config.container_workspace_dir}/tmp",
                user="sandbox",
                network_mode=self._config.network_mode,
                read_only=True,
                security_opt=["no-new-privileges"],
                mem_limit=self._config.mem_limit,
                cpu_quota=self._config.cpu_quota,
                cpu_period=100_000,
                tmpfs={"/tmp": "size=64m,noexec"},
                detach=True,
                auto_remove=False,
                # 孤儿清扫依据（app 侧 beat 任务按 label 扫描强删遗留容器）
                labels={
                    "agent-flow.sandbox": "true",
                    "agent-flow.sandbox-id": self._id,
                    "agent-flow.created-at": str(int(time.time())),
                },
            )
        except _DockerUnavailableError:
            raise
        except Exception as exc:
            raise _DockerUnavailableError(str(exc)) from exc

        try:
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", -1)
        except Exception:
            timed_out = True
            exit_code = -1
            with contextlib.suppress(Exception):
                container.kill()

        duration = time.monotonic() - start

        # stdout/stderr 分开取（合并调用会把 stderr 混进 stdout，stderr 丢失）
        try:
            stdout_raw = container.logs(stdout=True, stderr=False)
            stderr_raw = container.logs(stdout=False, stderr=True)
        except Exception:
            stdout_raw = b""
            stderr_raw = b""
        stdout_raw = stdout_raw if isinstance(stdout_raw, bytes) else b""
        stderr_raw = stderr_raw if isinstance(stderr_raw, bytes) else b""

        with contextlib.suppress(Exception):
            container.remove(force=True)

        stdout = _truncate(stdout_raw.decode("utf-8", "replace"), self._config.max_output_bytes)
        stderr = _truncate(stderr_raw.decode("utf-8", "replace"), self._config.max_output_bytes)

        if timed_out:
            stderr += f"\n[timeout] Command exceeded {timeout}s and was killed."

        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration=duration,
            timed_out=timed_out,
        )

    def _acquire_reused_container(self, client: Any) -> tuple[str, _RegistryEntry]:
        """获取（或创建/收养）当前 sandbox 的常驻容器。

        查找顺序：进程注册表 → daemon 按名收养（跨进程重启）→ 新建。
        丢弃已死条目；新建前按 max_containers 做 LRU 驱逐。
        返回 (容器名, 注册表条目)。
        """
        # docker 包缺失已在 _get_docker_client 统一转 _DockerUnavailableError；
        # 此处 import 仅取 errors.NotFound（mypy 对缺 stub 包只报一次，无需 ignore）
        import docker

        name = sandbox_container_name(
            self._mounts, self._config.image, self._config.network_mode
        )
        with _registry_lock:
            entry = _containers.get(name)
            if entry is not None:
                try:
                    entry.container.reload()
                    if entry.container.status == "running":
                        return name, entry
                except Exception:
                    pass
                # 容器已死/失联：剔除并兜底清理
                _containers.pop(name, None)
                with contextlib.suppress(Exception):
                    entry.container.remove(force=True)

            # daemon 收养（本进程没见过但 daemon 上有——后端重启场景）
            container: Any = None
            try:
                container = client.containers.get(name)
                container.reload()
                if container.status == "running":
                    logger.info("sandbox_container_adopted", container=name)
                    entry = _RegistryEntry(container)
                    _containers[name] = entry
                    return name, entry
                # 存在但已退出（exited/created/dead）→ 清掉走新建
                with contextlib.suppress(Exception):
                    container.remove(force=True)
            except docker.errors.NotFound:
                pass
            except Exception:
                # get/reload 失联等异常：清掉残骸后走新建（新建失败自然抛出）
                if container is not None:
                    with contextlib.suppress(Exception):
                        container.remove(force=True)

            # LRU 驱逐（持锁，含 remove 网络调用——acquire 阶段串行可接受，
            # exec 长过程不持锁）
            limit = self._config.max_containers
            while limit and len(_containers) >= limit:
                _evict_locked()

            container = client.containers.run(
                image=self._config.image,
                command=["sleep", "infinity"],
                name=name,
                volumes=self._build_volumes(),
                working_dir=f"{self._config.container_workspace_dir}/tmp",
                user="sandbox",
                network_mode=self._config.network_mode,
                read_only=True,
                security_opt=["no-new-privileges"],
                mem_limit=self._config.mem_limit,
                cpu_quota=self._config.cpu_quota,
                cpu_period=100_000,
                tmpfs={"/tmp": "size=64m,noexec"},
                detach=True,
                auto_remove=False,
                labels={
                    "agent-flow.sandbox": "true",
                    "agent-flow.sandbox-id": self._id,
                    "agent-flow.created-at": str(int(time.time())),
                },
            )
            entry = _RegistryEntry(container)
            _containers[name] = entry
            return name, entry

    def _exec_with_retry(
        self, client: Any, timeout: int, command: str, env: dict[str, str] | None
    ) -> tuple[int, bytes, bytes]:
        """在常驻容器内 exec 命令；容器死亡时重建并重试一次。

        单次 exec 完成 触碰 last-used + 执行 + 超时包裹（label 不可变，
        last-used 落容器内 tmpfs 供 beat 闲置回收）。返回 (exit_code, stdout, stderr)。
        """
        inner = f"date +%s > {SANDBOX_LAST_USED_FILE}; {command}"
        wrapped = ["timeout", "--kill-after=10", str(timeout), "bash", "-c", inner]
        exec_env = {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            **(env or {}),
        }
        workdir = f"{self._config.container_workspace_dir}/tmp"

        for attempt in (1, 2):
            name, entry = self._acquire_reused_container(client)
            with _registry_lock:
                entry.busy += 1
            try:
                code, out = entry.container.exec_run(
                    wrapped, user="sandbox", workdir=workdir,
                    environment=exec_env, demux=True,
                )
                stdout_raw = out[0] if isinstance(out, tuple) and isinstance(out[0], bytes) else b""
                stderr_raw = out[1] if isinstance(out, tuple) and isinstance(out[1], bytes) else b""
                with _registry_lock:
                    entry.last_used = time.monotonic()
                return code, stdout_raw, stderr_raw
            except Exception as exc:
                # 容器死亡（daemon 重启/OOM/手动删）：重建重试一次
                with _registry_lock:
                    _containers.pop(name, None)
                if attempt == 2:
                    raise
                logger.warning(
                    "sandbox_reused_exec_failed_recreating",
                    container=name,
                    error=str(exc),
                )
                with contextlib.suppress(Exception):
                    entry.container.remove(force=True)
            finally:
                with _registry_lock:
                    entry.busy -= 1
        raise AssertionError("unreachable")  # pragma: no cover

    def _execute_docker_reused(
        self, command: str, timeout: int, env: dict[str, str] | None = None
    ) -> SandboxResult:
        """复用模式执行：常驻容器 + exec（vs _execute_docker 的每命令冷启动）。"""
        client = _get_docker_client()
        start = time.monotonic()

        code, stdout_raw, stderr_raw = self._exec_with_retry(client, timeout, command, env)

        duration = time.monotonic() - start
        # timeout(1) 语义：124=TERM 到点、137=--kill-after KILL
        timed_out = code in (124, 137)

        stdout = _truncate(stdout_raw.decode("utf-8", "replace"), self._config.max_output_bytes)
        stderr = _truncate(stderr_raw.decode("utf-8", "replace"), self._config.max_output_bytes)
        if timed_out:
            stderr += f"\n[timeout] Command exceeded {timeout}s and was killed."

        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=-1 if timed_out else code,
            duration=duration,
            timed_out=timed_out,
        )

    def _execute_subprocess(
        self, command: str, timeout: int, *, env: dict[str, str] | None = None
    ) -> SandboxResult:
        """subprocess fallback（Docker 不可用时）。env 合并注入子进程，
        不污染宿主进程环境。"""
        tmp_dir = self._mounts.get("tmp", self._work_dir)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        start = time.monotonic()
        try:
            proc = subprocess.run(
                ["bash", "-c", command],
                cwd=str(tmp_dir),
                capture_output=True,
                timeout=timeout,
                env={**os.environ, **(env or {})},
            )
            duration = time.monotonic() - start
            return SandboxResult(
                stdout=self._truncate(proc.stdout.decode("utf-8", "replace")),
                stderr=self._truncate(proc.stderr.decode("utf-8", "replace")),
                exit_code=proc.returncode,
                duration=duration,
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return SandboxResult(
                stdout="",
                stderr=f"[timeout] Command exceeded {timeout}s and was killed.",
                exit_code=-1,
                duration=duration,
                timed_out=True,
            )

    # ── 文件操作（操作宿主机 work_dir，与 LocalSandbox 相同）────────

    def read_file(self, path: str) -> str:
        resolved = self._with_output_fallback(
            self._safe_resolve(path, for_write=False), path
        )
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")
        content = resolved.read_text(encoding="utf-8", errors="replace")
        return self._truncate(content)

    def write_file(self, path: str, content: str) -> None:
        """写文件到 output 目录（用户可见/可下载）。同文件并发经互斥锁串行。"""
        resolved = self._safe_resolve_output(path)
        with file_mutation_lock(resolved):
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")

    def edit_file_many(
        self,
        path: str,
        edits: Sequence[tuple[str, str]],
        *,
        replace_all: bool = False,
    ) -> str:
        """就地编辑工作区内文件（宿主机挂载目录，容器内产物可直接编辑）。

        互斥锁内 读全文 → 快照匹配 → 替换写回，语义与 LocalSandbox 相同
        （见 edit_ops.apply_edits）。
        """
        resolved = self._with_output_fallback(
            self._safe_resolve(path, for_write=False), path
        )
        self._reject_input_write(resolved, path)
        with file_mutation_lock(resolved):
            if not resolved.exists():
                raise FileNotFoundError(f"File not found: {path}")
            # newline=""：关闭 universal newlines 翻译，保留原始 \r\n（与
            # LocalSandbox.edit_file_many 一致）
            with resolved.open("r", encoding="utf-8", errors="replace", newline="") as f:
                content = f.read()
            new_content, message = apply_edits(
                content, edits, path=path, replace_all=replace_all
            )
            with resolved.open("w", encoding="utf-8", newline="") as f:
                f.write(new_content)
        return message

    def glob(self, path: str, pattern: str) -> list[str]:
        base = self._safe_resolve(path, for_write=False)
        if not base.exists():
            return []
        return sorted(str(p) for p in base.glob(pattern))

    def grep(self, path: str, pattern: str) -> list[GrepMatch]:
        base = self._safe_resolve(path, for_write=False)
        if not base.exists():
            return []
        regex = re.compile(pattern)
        matches: list[GrepMatch] = []
        files = [base] if base.is_file() else list(base.rglob("*"))
        for f in files:
            if not f.is_file():
                continue
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if regex.search(line):
                    matches.append(GrepMatch(path=str(f), line_number=i, line=line))
        return matches

    # ── 内部 helpers（与 LocalSandbox 相同）──────────────────────────

    def _safe_resolve(self, user_path: str, *, for_write: bool) -> Path:
        """解析路径并校验在允许目录内（防路径越权）。

        workspace 模式（work_dir 为 {root}/tmp）：绝对路径剥容器风格前缀
        （workspace/，容器内挂载点）后按 tmp/ output/ input/ 前缀映射到
        对应宿主目录，裸相对路径默认 work_dir；白名单为工作区各目录
        （root/output/input）树内。非 workspace 模式保持旧行为：绝对路径
        剥前缀映射进 work_dir，白名单 work_dir 树内。
        """
        allowed: tuple[Path, ...]
        if self._workspace_mode:
            rel = user_path.lstrip("/") if os.path.isabs(user_path) else user_path
            if rel.startswith("workspace/"):
                rel = rel[len("workspace/"):]
            resolved = self._map_workspace_rel(rel).resolve()
            allowed = (self._root, self._output_dir, self._input_dir)
        else:
            if os.path.isabs(user_path):
                rel = user_path.lstrip('/')
                for prefix in ('tmp/', 'workspace/tmp/', 'workspace/'):
                    if rel.startswith(prefix):
                        rel = rel[len(prefix):]
                        break
                resolved = (self._work_dir / rel).resolve()
            else:
                resolved = (self._work_dir / user_path).resolve()
            allowed = (self._work_dir,)
        # 白名单校验：resolved 必须在允许目录树内
        if not any(_is_within(resolved, base) for base in allowed):
            msg = f"Access denied — path '{user_path}' outside sandbox work_dir"
            raise PermissionError(msg)
        return resolved

    def _map_workspace_rel(self, rel: str) -> Path:
        """工作区相对路径 → 实际宿主目录；无目录前缀默认 work_dir（tmp）。"""
        if rel.startswith('tmp/'):
            return self._work_dir / rel[len('tmp/'):]
        if rel.startswith('output/'):
            return self._output_dir / rel[len('output/'):]
        if rel.startswith('input/'):
            return self._input_dir / rel[len('input/'):]
        return self._work_dir / rel

    def _with_output_fallback(self, resolved: Path, user_path: str) -> Path:
        """裸相对路径在 tmp 下不存在时回退查 output/（write 产物在 output）。"""
        if (
            resolved.exists()
            or not user_path
            or os.path.isabs(user_path)
            or not self._workspace_mode
            or user_path.startswith(('tmp/', 'output/', 'input/'))
        ):
            return resolved
        alt = (self._output_dir / user_path).resolve()
        return alt if alt.exists() else resolved

    def _reject_input_write(self, resolved: Path, user_path: str) -> None:
        """input 为只读输入目录（容器内只读挂载），禁止写入/编辑。"""
        if self._workspace_mode and _is_within(resolved, self._input_dir):
            msg = (
                f"Access denied — path '{user_path}' is read-only input; "
                "copy it into the workspace to modify"
            )
            raise PermissionError(msg)

    def _safe_resolve_output(self, user_path: str) -> Path:
        """解析路径并校验是否在 output_dir 内（防路径越权）。

        当模型传入绝对路径时,提取相对部分映射到 output_dir 内。
        """
        output_dir = self._output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        if os.path.isabs(user_path):
            rel = user_path.lstrip('/')
            for prefix in ('output/', 'workspace/output/', 'workspace/'):
                if rel.startswith(prefix):
                    rel = rel[len(prefix):]
                    break
            resolved = (output_dir / rel).resolve()
        else:
            resolved = (output_dir / user_path).resolve()
        # 白名单校验：resolved 必须在 output_dir 树内
        try:
            resolved.relative_to(output_dir)
        except ValueError as exc:
            msg = f"Access denied — path '{user_path}' outside sandbox output_dir"
            raise PermissionError(msg) from exc
        return resolved

    def _truncate(self, text: str) -> str:
        if len(text) <= self._max_output:
            return text
        return text[: self._max_output] + f"\n... [truncated: {len(text):,} chars]"


def _truncate(text: str, max_bytes: int) -> str:
    """模块级截断 helper（Docker logs 用）。"""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", "ignore")
    return truncated + f"\n\n[truncated — output exceeded {max_bytes} bytes]"


__all__ = [
    "DockerSandbox",
    "DockerSandboxConfig",
    "SANDBOX_LAST_USED_FILE",
    "remove_sandbox_container",
    "sandbox_container_name",
]
