"""Checkpointer factory with explicit dependency injection.

The harness is backend-agnostic: it never imports ``app.core.config`` or
``app.db.mongodb``. Callers hand in a pre-built checkpoint saver (typically a
``MongoDBSaver`` constructed in the application layer), so the harness itself
has no hard dependency on motor / pymongo. The :mod:`langgraph.checkpoint.mongodb`
import is deferred to call time so that ``import agent_flow_harness`` works even
when the optional MongoDB checkpointer backend is not installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.base import BaseCheckpointSaver

if TYPE_CHECKING:
    from langgraph.checkpoint.mongodb import MongoDBSaver

_saver: BaseCheckpointSaver[Any] | None = None


def configure_checkpointer(
    saver: BaseCheckpointSaver[Any],
    *,
    overwrite: bool = False,
) -> BaseCheckpointSaver[Any]:
    """Configure and return the shared checkpointer singleton.

    The harness does not construct the saver itself; the application layer
    builds it (e.g. ``MongoDBSaver(client=..., db_name=...)``) and injects it
    here at startup.

    Args:
        saver: A fully-constructed checkpoint saver (sync or async).
        overwrite: When ``True`` the existing singleton is replaced. Useful
            for tests that build multiple harnesses per process.
    """
    global _saver  # noqa: PLW0603
    if _saver is None or overwrite:
        _saver = saver
    return _saver


def get_checkpointer() -> BaseCheckpointSaver[Any]:
    """Return the previously-configured checkpointer.

    Raises:
        RuntimeError: If :func:`configure_checkpointer` was never called.
    """
    if _saver is None:
        msg = (
            "agent_flow_harness checkpointer is not configured; call "
            "configure_checkpointer(saver) once at startup."
        )
        raise RuntimeError(msg)
    return _saver


def reset_checkpointer() -> None:
    """Drop the cached singleton (test helper)."""
    global _saver  # noqa: PLW0603
    _saver = None


def build_mongo_saver(
    client: Any,
    db_name: str,
) -> MongoDBSaver:
    """Construct a :class:`MongoDBSaver` from an injected PyMongo client.

    Convenience helper kept here so applications that *do* want MongoDB can
    build a saver without importing langgraph's mongo module themselves. The
    import is deferred: the harness still imports cleanly when
    ``langgraph-checkpoint-mongodb`` is absent.

    Raises:
        ImportError: If ``langgraph-checkpoint-mongodb`` is not installed.
    """
    try:
        from langgraph.checkpoint.mongodb import MongoDBSaver
    except ImportError:  # pragma: no cover - environment dependent
        msg = (
            "langgraph-checkpoint-mongodb is required to build a MongoDBSaver; "
            "install it or inject a pre-built saver via configure_checkpointer()."
        )
        raise ImportError(msg) from None
    return MongoDBSaver(client=client, db_name=db_name)
