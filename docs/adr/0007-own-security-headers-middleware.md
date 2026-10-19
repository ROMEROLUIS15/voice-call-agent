# ADR 0007: Own security headers middleware

*   **Status:** Accepted
*   **Date:** 2026-10-18

## Context
Every HTTP response must carry security headers (the equivalent of `helmet` in Node.js): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `Cache-Control: no-store`, and `Strict-Transport-Security` in production, without a `Server` header. The service has no browser clients: its only callers are Twilio, Meta and load balancers. The header set is therefore fixed and small.

## Decision
A pure ASGI middleware of our own (`http_hardening/security_headers.py`, ~50 lines) that wraps the **whole** application from the outside. It also covers the `500` responses produced by Starlette's error middleware and the denial responses of WebSocket handshakes, and it removes any `server` header the application sets. uvicorn's own `Server` header is disabled in its configuration (`server_header=False`), because no middleware can remove it.

## Alternatives considered
*   **The `secure` library (2.0.1).** Not chosen, although it is well built (typed, no dependencies, an ASGI middleware). Its presets target browser applications: STRICT sets `default-src 'self'`, `script-src`, COEP and COOP, so almost every value would have to be overridden to reach the fixed set above. Its middleware handles HTTP scopes only. It would add a dependency to the request path for a static list of headers.
*   **Starlette's `add_middleware`.** Not chosen as the mechanism: user middleware runs inside `ServerErrorMiddleware`, so `500` responses would leave without the headers.

## Consequences
*   Easier: an exact, reviewable header set with no third-party code in the request path; tests assert every header on `200`, `404`, `422`, `500` and `413` responses, and mutation tests prove they fail when a header is dropped.
*   Harder: new header recommendations do not arrive with a library update; the header set is reviewed with the threat model (`docs/security/threat-model.md`).
