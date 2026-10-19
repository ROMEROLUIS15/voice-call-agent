"""Rate limiting per client address and route on the call entries.

The client address is the one uvicorn resolved: `X-Forwarded-For` counts only when the request
comes from a trusted proxy (`TRUSTED_PROXY_ADDRESSES`).
"""

import math
import time

from limits import RateLimitItem, parse
from limits.aio.storage import Storage
from limits.aio.strategies import MovingWindowRateLimiter
from limits.storage import storage_from_string
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from voice_call_agent.http_hardening.error_responses import error_body
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode

_POLICY_VIOLATION = 1008


class RateLimitStorageError(ValueError):
    """The storage URI does not name an asynchronous `limits` storage."""


def build_rate_limiter(storage_uri: str) -> MovingWindowRateLimiter:
    """Limiter over the configured storage (in memory per instance, or a shared one)."""
    storage = storage_from_string(storage_uri)
    if not isinstance(storage, Storage):
        raise RateLimitStorageError(f"'{storage_uri}' is not an async storage (use 'async+…')")
    return MovingWindowRateLimiter(storage)


class RequestRateLimitMiddleware:
    """Rejects requests beyond the limit: `429` on HTTP, a refused handshake on WebSockets."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: MovingWindowRateLimiter,
        limit: str,
        protected_paths: frozenset[str],
    ) -> None:
        self._app = app
        self._limiter = limiter
        self._limit: RateLimitItem = parse(limit)
        self._protected_paths = protected_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or scope["path"] not in self._protected_paths:
            await self._app(scope, receive, send)
            return
        client = scope.get("client")
        address = client[0] if client else "unknown"
        if await self._limiter.hit(self._limit, address, scope["path"]):
            await self._app(scope, receive, send)
            return
        report_error(ErrorCode.RATE_LIMITED, path=scope["path"])
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": _POLICY_VIOLATION})
            return
        await self._reject(address, scope, receive, send)

    async def _reject(self, address: str, scope: Scope, receive: Receive, send: Send) -> None:
        stats = await self._limiter.get_window_stats(self._limit, address, scope["path"])
        retry_after = max(math.ceil(stats.reset_time - time.time()), 1)
        response = JSONResponse(
            error_body(429), status_code=429, headers={"Retry-After": str(retry_after)}
        )
        await response(scope, receive, send)
