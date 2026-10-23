"""复用沙盒容器的显式销毁钩子 — session/task 删除时同步清理。

空闲回收（beat 60s 轮询）是兜底；本模块让容器随工作区立即消失，
不留 5 分钟尾巴。多节点部署下只能删本节点 daemon 上的容器，其他
节点的遗留仍靠闲置回收（与现有清扫任务同限制）。
"""
from pathlib import Path

from loguru import logger


def destroy_workspace_sandbox(root: Path) -> None:
    """删除 workspace 对应的复用容器（幂等，绝不抛异常）。

    root 为工作区根目录（{workspaces}/{user_id}/{session_id} 或
    .../tasks/{task_id}），mounts 布局与 resolve_harness_context 的
    bash 沙箱一致：tmp/input/output 三个子目录。
    """
    from app.core.config import settings

    if not settings.SANDBOX_ENABLED or not settings.SANDBOX_REUSE_CONTAINER:
        return
    try:
        from agent_flow_harness.sandbox.docker import (
            remove_sandbox_container,
            sandbox_container_name,
        )

        name = sandbox_container_name(
            {
                "tmp": root / "tmp",
                "input": root / "input",
                "output": root / "output",
            },
            image=settings.SANDBOX_IMAGE,
            network_mode=settings.SANDBOX_NETWORK_MODE,
        )
        if remove_sandbox_container(name):
            logger.info("sandbox_container_destroyed", container=name, workspace=str(root))
    except Exception as exc:
        # 清理失败不阻塞删除流程；闲置回收兜底
        logger.warning("sandbox_container_destroy_failed", workspace=str(root), error=str(exc))


__all__ = ["destroy_workspace_sandbox"]
