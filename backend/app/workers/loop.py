"""Shared persistent event loop for Celery worker async tasks.

Celery tasks are synchronous functions, but our workflow engine is async
(motor, asyncio.gather, etc.). Each Celery *worker process* must reuse a
single event loop across all task invocations — otherwise motor's
``AsyncIOMotorClient`` (a process-wide singleton in ``app.db.mongodb``)
gets bound to one loop and then used from another, raising:

    RuntimeError: ... got Future ... attached to a different loop

Before this module, ``scheduled_workflow.py`` and ``workflow_execution.py``
each maintained their *own* ``_loop`` global. When the same worker process
ran both task types, the second one created a new loop while the motor
client was still pinned to the first → the error above.

Fix: a single process-wide loop here, imported by every Celery task.
"""
from __future__ import annotations

import asyncio

_loop: asyncio.AbstractEventLoop | None = None


def get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return the process-wide event loop for this Celery worker process.

    Lazily creates a new loop on first call, then reuses it for every
    subsequent task in this process. The loop is never closed during the
    worker's lifetime.
    """
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop


def run_async(coro):
    """Run an async coroutine on the shared worker loop to completion.

    Convenience wrapper around ``get_worker_loop().run_until_complete(coro)``.
    """
    return get_worker_loop().run_until_complete(coro)
