"""External API call log service.

Persists one document per ``/api/v1/ext/*`` call for audit and token
statistics. Two-phase write model:

1. Phase 1 (``auth_and_rate_limit`` dependency): stash the full call
   context (api_key_id / user identity / endpoint / agent_id / session_id
   / request_id) on a request-scoped ContextVar. NO database write yet —
   token usage is unknown at this point.

2. Phase 2 (``AgentExecutionService._run()`` finally block): read the
   stashed context + token usage from the harness middleware summary,
   then ``insert_one`` the complete log document.

3. Fallback (``ExtApiStatsMiddleware`` response phase): if phase 2 did
   NOT consume the context (e.g. 401 / 403 / 500 before agent execution),
   the middleware writes a token-less record so failed calls are still
   audited. The ContextVar flag ``consumed`` distinguishes the two paths.

Workflow path: tasks triggered by agents run in a Celery worker
(cross-process), so their token consumption lives on the task document
(``total_tokens``) linked back via ``source_session_id``. Workflow calls
to ``/ext/workflows/{id}/invoke`` are logged here with ``total_tokens=0``;
to compute full session consumption, the caller joins ``tasks`` by
``source_session_id``.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from app.db.mongodb import get_database
from app.models.base import utc_now
from app.models.ext_api_call_log import ExtApiCallLog

# ---------------------------------------------------------------------------
# Request-scoped context (set in auth_and_rate_limit, read by phase 2)
# ---------------------------------------------------------------------------


@dataclass
class ExtCallContext:
    """Stashed call context — populated by ``auth_and_rate_limit``."""

    api_key_id: str
    owner_user_id: str
    user_sub: str = ""
    visitor_id: str = ""
    auth_mode: str = "legacy"
    endpoint: str = ""
    request_id: str = ""
    start_time_ms: int = 0
    # Filled lazily by route handlers once known:
    agent_id: str = ""
    workflow_id: str = ""
    session_id: str = ""
    task_id: str = ""
    # Set to True by phase 2 once the log has been written, so the
    # middleware fallback knows to skip.
    consumed: bool = False
    # Free-form metadata for ad-hoc attribution (e.g. introspect_stale flag).
    extra: dict[str, Any] = field(default_factory=dict)


_ext_call_ctx: ContextVar[ExtCallContext | None] = ContextVar(
    "ext_call_ctx", default=None
)


def set_ext_call_context(ctx: ExtCallContext) -> None:
    """Attach call context to the current async context."""
    _ext_call_ctx.set(ctx)


def get_ext_call_context() -> ExtCallContext | None:
    """Read the stashed call context (or None if not an ext request)."""
    return _ext_call_ctx.get()


def update_ext_call_context(**updates: Any) -> None:
    """Patch fields on the stashed context (e.g. agent_id / session_id)."""
    ctx = _ext_call_ctx.get()
    if ctx is None:
        return
    for k, v in updates.items():
        if v:
            setattr(ctx, k, v)


def clear_ext_call_context() -> None:
    """Reset to None (defensive; mainly for tests)."""
    _ext_call_ctx.set(None)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ExtApiCallLogService:
    """CRUD + queries for ``ext_api_call_logs``."""

    COLLECTION = "ext_api_call_logs"
    TTL_SECONDS = 90 * 86400  # 90 days

    @staticmethod
    def _collection():
        return get_database()[ExtApiCallLogService.COLLECTION]

    # ── Indexes ──

    @staticmethod
    async def ensure_indexes() -> None:
        col = ExtApiCallLogService._collection()
        await col.create_index(
            [("api_key_id", 1), ("timestamp", -1)],
            name="idx_ext_logs_key_time",
        )
        await col.create_index(
            [("api_key_id", 1), ("user_sub", 1), ("timestamp", -1)],
            name="idx_ext_logs_user_time",
        )
        await col.create_index(
            [("api_key_id", 1), ("visitor_id", 1), ("timestamp", -1)],
            name="idx_ext_logs_visitor_time",
        )
        await col.create_index("request_id", name="idx_ext_logs_request_id")
        # TTL: timestamp MUST be a BSON date for the TTL monitor to expire docs.
        await col.create_index(
            "timestamp",
            expireAfterSeconds=ExtApiCallLogService.TTL_SECONDS,
            name="idx_ext_logs_ttl",
        )
        logger.info("ExtApiCallLog indexes ensured")

    # ── Write ──

    @staticmethod
    async def write_log(
        ctx: ExtCallContext,
        *,
        status: str,
        status_code: int,
        error_code: str = "",
        latency_ms: int = 0,
        total_tokens: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        llm_calls: int = 0,
    ) -> str | None:
        """Insert one call log document. Returns inserted id (or None on failure).

        Failures are logged but never raised — logging must not break the
        user-facing request flow.
        """
        doc = ExtApiCallLog(
            api_key_id=ctx.api_key_id,
            owner_user_id=ctx.owner_user_id,
            user_sub=ctx.user_sub,
            visitor_id=ctx.visitor_id,
            auth_mode=ctx.auth_mode,
            endpoint=ctx.endpoint,
            agent_id=ctx.agent_id,
            workflow_id=ctx.workflow_id,
            session_id=ctx.session_id,
            task_id=ctx.task_id,
            request_id=ctx.request_id,
            status=status,
            status_code=status_code,
            error_code=error_code,
            latency_ms=latency_ms,
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            llm_calls=llm_calls,
        )
        try:
            payload = doc.model_dump(by_alias=True)
            await ExtApiCallLogService._collection().insert_one(payload)
            return doc.id
        except Exception as exc:
            logger.warning(
                "ext_call_log_write_failed",
                api_key_id=ctx.api_key_id,
                request_id=ctx.request_id,
                error=str(exc),
            )
            return None

    # ── Queries ──

    @staticmethod
    async def list_logs(
        api_key_id: str,
        *,
        user_sub: str | None = None,
        visitor_id: str | None = None,
        session_id: str | None = None,
        endpoint: str | None = None,
        start: str | None = None,
        end: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        """Paginated log query. Returns (items, total)."""
        from datetime import datetime

        query: dict[str, Any] = {"api_key_id": api_key_id}
        if user_sub:
            query["user_sub"] = user_sub
        if visitor_id:
            query["visitor_id"] = visitor_id
        if session_id:
            query["session_id"] = session_id
        if endpoint:
            query["endpoint"] = endpoint
        if start or end:
            ts: dict[str, Any] = {}
            try:
                if start:
                    ts["$gte"] = datetime.fromisoformat(start)
            except ValueError:
                pass
            try:
                if end:
                    ts["$lt"] = datetime.fromisoformat(end)
            except ValueError:
                pass
            if ts:
                query["timestamp"] = ts

        col = ExtApiCallLogService._collection()
        total = await col.count_documents(query)
        cursor = (
            col.find(query, {"_id": 0})
            .sort("timestamp", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        items = await cursor.to_list(length=page_size)
        # Convert datetime → ISO string for JSON serialization
        for it in items:
            ts = it.get("timestamp")
            if hasattr(ts, "isoformat"):
                it["timestamp"] = ts.isoformat()
        return items, total

    @staticmethod
    async def get_token_summary(
        api_key_id: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate token totals for an API Key (optionally time-windowed)."""
        from datetime import datetime

        match: dict[str, Any] = {"api_key_id": api_key_id}
        if start or end:
            ts: dict[str, Any] = {}
            try:
                if start:
                    ts["$gte"] = datetime.fromisoformat(start)
            except ValueError:
                pass
            try:
                if end:
                    ts["$lt"] = datetime.fromisoformat(end)
            except ValueError:
                pass
            if ts:
                match["timestamp"] = ts

        pipeline = [
            {"$match": match},
            {
                "$group": {
                    "_id": None,
                    "total_tokens": {"$sum": "$total_tokens"},
                    "input_tokens": {"$sum": "$input_tokens"},
                    "output_tokens": {"$sum": "$output_tokens"},
                    "calls": {"$sum": 1},
                }
            },
        ]
        col = ExtApiCallLogService._collection()
        cursor = col.aggregate(pipeline)
        rows = await cursor.to_list(length=1)
        if not rows:
            return {
                "total_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "calls": 0,
            }
        r = rows[0]
        return {
            "total_tokens": r.get("total_tokens", 0),
            "input_tokens": r.get("input_tokens", 0),
            "output_tokens": r.get("output_tokens", 0),
            "calls": r.get("calls", 0),
        }

    @staticmethod
    async def get_users_summary(
        api_key_id: str,
        *,
        period_days: int = 7,
    ) -> list[dict[str, Any]]:
        """Top users by token consumption in the last ``period_days`` days."""
        from datetime import timedelta

        since = (utc_now() - timedelta(days=period_days))
        match = {
            "api_key_id": api_key_id,
            "timestamp": {"$gte": since},
            # Skip legacy-mode entries (no user_sub) — those are attributed
            # by visitor_id instead. Caller can do a separate query if needed.
            "user_sub": {"$ne": ""},
        }
        pipeline = [
            {"$match": match},
            {
                "$group": {
                    "_id": "$user_sub",
                    "calls": {"$sum": 1},
                    "total_tokens": {"$sum": "$total_tokens"},
                    "last_seen_at": {"$max": "$timestamp"},
                }
            },
            {"$sort": {"total_tokens": -1}},
            {"$limit": 100},
        ]
        col = ExtApiCallLogService._collection()
        cursor = col.aggregate(pipeline)
        rows = await cursor.to_list(length=100)
        result = []
        for r in rows:
            last = r.get("last_seen_at")
            result.append({
                "user_sub": r["_id"],
                "calls": r.get("calls", 0),
                "total_tokens": r.get("total_tokens", 0),
                "last_seen_at": last.isoformat() if hasattr(last, "isoformat") else "",
            })
        return result
