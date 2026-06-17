"""Circuit breaker — per-tool fault isolation.

Implements the classic three-state circuit breaker pattern:

    ┌─────────┐  failures >= threshold  ┌───────┐
    │ CLOSED  │ ──────────────────────→ │ OPEN  │
    │ (normal)│                         │(block) │
    └─────────┘                         └───────┘
         ↑                                   │
         │     success                       │ timeout expires
         │  ┌───────────┐                    ↓
         └──┤ HALF_OPEN │ ←──────────┐ ┌──────────┐
            │ (probe)   │    failure  │ │ timeout  │
            └───────────┘─────────────┘ │ (wait)   │
                success → CLOSED        └──────────┘

Each tool gets its own breaker instance so one flaky tool doesn't
affect others.
"""
from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass, field

from loguru import logger


class CircuitState(enum.Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failures exceeded threshold — reject calls
    HALF_OPEN = "half_open"  # Probing — allow one test call


@dataclass
class CircuitBreaker:
    """Per-tool circuit breaker.

    Args:
        name: Identifier for logging (typically the tool name).
        failure_threshold: Number of failures within *window_seconds* to
            transition from CLOSED → OPEN.
        window_seconds: Sliding window for counting failures.
        recovery_timeout: Seconds to wait in OPEN state before transitioning
            to HALF_OPEN for a probe call.

    Thread-safe: all state mutations are guarded by a lock.
    """

    name: str
    failure_threshold: int = 3
    window_seconds: float = 60.0
    recovery_timeout: float = 30.0

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_timestamps: list[float] = field(default_factory=list, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        """Current circuit state (transitions OPEN → HALF_OPEN on timeout)."""
        with self._lock:
            return self._get_state_locked()

    def allow_request(self) -> bool:
        """Return True if a call is permitted, False if circuit is OPEN."""
        with self._lock:
            state = self._get_state_locked()
            if state == CircuitState.CLOSED:
                return True
            if state == CircuitState.HALF_OPEN:
                return True  # Allow one probe call
            return False  # OPEN

    def record_success(self) -> None:
        """Record a successful call — resets failures and closes circuit."""
        with self._lock:
            prev = self._state
            self._state = CircuitState.CLOSED
            self._failure_timestamps.clear()
            if prev != CircuitState.CLOSED:
                logger.info(
                    "circuit_breaker_closed",
                    tool=self.name,
                    previous_state=prev.value,
                )

    def record_failure(self) -> None:
        """Record a failed call — may trip the circuit to OPEN."""
        now = time.monotonic()
        with self._lock:
            self._last_failure_time = now
            self._failure_timestamps.append(now)

            # Prune old timestamps outside the window
            cutoff = now - self.window_seconds
            self._failure_timestamps = [
                t for t in self._failure_timestamps if t > cutoff
            ]

            if len(self._failure_timestamps) >= self.failure_threshold:
                prev = self._state
                self._state = CircuitState.OPEN
                if prev != CircuitState.OPEN:
                    logger.warning(
                        "circuit_breaker_opened",
                        tool=self.name,
                        failures=len(self._failure_timestamps),
                        window=f"{self.window_seconds}s",
                    )

    def reset(self) -> None:
        """Manually reset the circuit to CLOSED."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_timestamps.clear()

    # ── Internal ────────────────────────────────────────────────────────

    def _get_state_locked(self) -> CircuitState:
        """Return current state, transitioning OPEN → HALF_OPEN if timeout expired.

        Must be called while holding ``self._lock``.
        """
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "circuit_breaker_half_open",
                    tool=self.name,
                    recovery_timeout=f"{self.recovery_timeout}s",
                )
        return self._state


# ── Global registry ───────────────────────────────────────────────────────────

_breakers: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(
    tool_name: str,
    failure_threshold: int = 3,
    window_seconds: float = 60.0,
    recovery_timeout: float = 30.0,
) -> CircuitBreaker:
    """Return (or create) the circuit breaker for a given tool.

    Breakers are cached globally so each tool has exactly one instance.
    """
    with _registry_lock:
        if tool_name not in _breakers:
            _breakers[tool_name] = CircuitBreaker(
                name=tool_name,
                failure_threshold=failure_threshold,
                window_seconds=window_seconds,
                recovery_timeout=recovery_timeout,
            )
        return _breakers[tool_name]


def is_tool_available(tool_name: str) -> bool:
    """Check if a tool's circuit breaker allows requests.

    Returns ``True`` if the tool is available, ``False`` if tripped.
    """
    breaker = get_breaker(tool_name)
    return breaker.allow_request()


def record_tool_result(tool_name: str, success: bool) -> None:
    """Record a tool execution result for circuit breaker tracking."""
    breaker = get_breaker(tool_name)
    if success:
        breaker.record_success()
    else:
        breaker.record_failure()
