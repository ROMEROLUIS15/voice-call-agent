"""Signed requests to Cronix's phone agent API (docs/specs/cronix-phone-api-contract.md §2, §6, §7).

Every request carries `X-Cronix-Timestamp` and `X-Cronix-Signature`, an HMAC-SHA256 of
`timestamp.METHOD.route.body` with the shared secret, where `route` is the path from `/v1/` with
its query string. A request is retried once on a 429, a 503, a timeout or a connection failure:
reads are safe to repeat, and every write carries its idempotency key, so a repeated booking
returns the stored answer instead of booking twice.

Requests share one connection pool: a new connection per request paid its TLS handshake on every
availability check. With a region set, each request carries `x-region`, so the API's functions
run next to its database instead of next to the caller (measured 2026-11-11 against production:
a median of 1,339 ms per availability check before, 589 ms with both).
"""

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any

import aiohttp

from voice_call_agent.scheduling_backend.scheduling_errors import (
    IdempotencyKeyReusedError,
    SchedulingBackendRejectedRequestError,
    SchedulingBackendUnavailableError,
)
from voice_call_agent.settings.sections import SchedulingApiSettings

JsonObject = dict[str, Any]  # Any: JSON values as the API returns them.

_RETRIED_STATUSES = frozenset({429, 503})
_KEEPALIVE_S = 120.0


def signature(secret: str, timestamp: str, method: str, route: str, body: str) -> str:
    message = f"{timestamp}.{method}.{route}.{body}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


class SignedApi:
    """Signed GET and POST requests to the API, with its timeouts and its one retry."""

    def __init__(
        self, settings: SchedulingApiSettings, clock: Callable[[], float] = time.time
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._http: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        """Closes the pooled connections; a later request opens new ones."""
        if self._http is not None:
            await self._http.close()
            self._http = None

    async def get(self, route: str) -> JsonObject:
        return await self._send("GET", route, "", self._settings.read_timeout_seconds, None)

    async def post(
        self, route: str, body: JsonObject, *, idempotency_key: str | None = None
    ) -> JsonObject:
        limit_s = self._settings.write_timeout_seconds
        return await self._send("POST", route, json.dumps(body), limit_s, idempotency_key)

    async def _send(
        self, method: str, route: str, body: str, limit_s: float, idempotency_key: str | None
    ) -> JsonObject:
        for attempt in (1, 2):
            try:
                status, payload = await self._once(method, route, body, limit_s, idempotency_key)
            except (aiohttp.ClientError, TimeoutError) as error:
                if attempt == 2:
                    raise SchedulingBackendUnavailableError(f"{method} {_path(route)}") from error
                continue
            if status in _RETRIED_STATUSES:
                if attempt == 2:
                    raise SchedulingBackendUnavailableError(f"{method} {_path(route)}: {status}")
                continue
            if status == 409:
                raise IdempotencyKeyReusedError(f"{method} {_path(route)}")
            if status != 200 or not isinstance(payload, dict):
                raise SchedulingBackendRejectedRequestError(f"{method} {_path(route)}: {status}")
            return payload
        raise AssertionError("unreachable: the second attempt returns or raises")

    async def _once(
        self, method: str, route: str, body: str, limit_s: float, idempotency_key: str | None
    ) -> tuple[int, object]:
        timestamp = str(int(self._clock()))
        secret = self._settings.signing_secret.get_secret_value()
        headers = {
            "X-Cronix-Timestamp": timestamp,
            "X-Cronix-Signature": signature(secret, timestamp, method, route, body),
            "Content-Type": "application/json",
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        if self._settings.region is not None:
            headers["x-region"] = self._settings.region
        async with self._session().request(
            method,
            self._settings.base_url + route,
            data=body or None,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=limit_s),
        ) as response:
            payload: object = None
            if response.content_type == "application/json":
                payload = await response.json()
            return response.status, payload

    def _session(self) -> aiohttp.ClientSession:
        """The pooled session, opened on the first request: it needs the running event loop."""
        if self._http is None or self._http.closed:
            # aiohttp drops an idle connection after 15 s, shorter than a caller's pause between
            # two checks; the API's side kept one open after 70 s idle (measured 2026-11-11).
            keepalive = aiohttp.TCPConnector(keepalive_timeout=_KEEPALIVE_S)
            self._http = aiohttp.ClientSession(connector=keepalive)
        return self._http


def _path(route: str) -> str:
    """The route without its query string: errors never carry a call's parameters."""
    return route.split("?", 1)[0]
