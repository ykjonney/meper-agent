"""沙盒镜像预拉取 — API/worker 启动后台预热。

首笔沙盒执行若撞上镜像未拉取，要付整镜像的 pull 耗时（数百 MB），
且当前 DockerSandbox 的降级闸会把它当 docker 不可用处理。启动时后台
``images.get`` 检查、缺失才 ``images.pull``，把这笔成本挪到启动期。

调用方负责放后台线程/``asyncio.to_thread``（本模块内是阻塞 I/O），
任何失败只记日志、不阻断启动。
"""
from loguru import logger


def ensure_sandbox_image() -> None:
    """检查并按需预拉沙盒镜像（阻塞调用）。"""
    from app.core.config import settings

    if not settings.SANDBOX_ENABLED:
        return
    try:
        import docker
    except ImportError:
        logger.warning("sandbox_prepull_skipped", reason="docker package not installed")
        return

    try:
        client = docker.from_env(timeout=60)
        try:
            client.images.get(settings.SANDBOX_IMAGE)
            logger.debug("sandbox_image_present", image=settings.SANDBOX_IMAGE)
            return
        except docker.errors.ImageNotFound:
            pass
        logger.info("sandbox_image_pull_start", image=settings.SANDBOX_IMAGE)
        client.images.pull(settings.SANDBOX_IMAGE)
        logger.info("sandbox_image_pull_done", image=settings.SANDBOX_IMAGE)
    except Exception as exc:
        # daemon 不可达/网络失败等 —— 沙盒降级闸已有兜底，这里不阻断启动
        logger.warning(
            "sandbox_prepull_failed",
            image=settings.SANDBOX_IMAGE,
            error=str(exc),
        )


__all__ = ["ensure_sandbox_image"]
