"""AC6 cover: checkpointer injection contract."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from agent_flow_harness.checkpointer import (
    configure_checkpointer,
    get_checkpointer,
    reset_checkpointer,
)


@pytest.fixture(autouse=True)
def _isolate_saver():
    """Each test starts with no configured saver."""
    reset_checkpointer()
    yield
    reset_checkpointer()


def test_get_before_configure_raises() -> None:
    with pytest.raises(RuntimeError):
        get_checkpointer()


def test_configure_returns_injected_saver() -> None:
    saver = MemorySaver()
    returned = configure_checkpointer(saver)
    assert returned is saver
    assert get_checkpointer() is saver


def test_configure_overwrite_replaces_singleton() -> None:
    first = MemorySaver()
    second = MemorySaver()
    configure_checkpointer(first)
    assert get_checkpointer() is first
    configure_checkpointer(second, overwrite=True)
    assert get_checkpointer() is second


def test_reset_clears_singleton() -> None:
    configure_checkpointer(MemorySaver())
    reset_checkpointer()
    with pytest.raises(RuntimeError):
        get_checkpointer()
