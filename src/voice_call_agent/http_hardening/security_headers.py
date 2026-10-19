"""Security headers on every HTTP response (ADR 0007)."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The service has no browser clients: nothing may be framed, scripted, sniffed or cached.
_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"cache-control", b"no-store"),
)
_HSTS_HEADER = (b"strict-transport-security", b"max-age=63072000; includeSubDomains")
# Headers the application may not set: these are owned here, and `server` reveals the stack.
_REPLACED = frozenset({name for name, _ in _SECURITY_HEADERS} | {_HSTS_HEADER[0], b"server"})
_RESPONSE_START = frozenset({"http.response.start", "websocket.http.response.start"})


class SecurityHeadersMiddleware:
    """Pure ASGI middleware wrapping the whole application.

    It wraps the app from the outside, so it also covers the `500` responses Starlette's
    error middleware produces and the denial responses of WebSocket handshakes.
    """

    def __init__(self, app: ASGIApp, *, strict_transport_security: bool) -> None:
        self._app = app
        self._headers = (
            (*_SECURITY_HEADERS, _HSTS_HEADER) if strict_transport_security else _SECURITY_HEADERS
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] in _RESPONSE_START:
                kept = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in _REPLACED
                ]
                message = {**message, "headers": [*kept, *self._headers]}
            await send(message)

        await self._app(scope, receive, send_with_headers)
