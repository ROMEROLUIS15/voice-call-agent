"""Wraps the application with every HTTP protection, in the order they must apply."""

from collections.abc import Mapping

from fastapi import FastAPI
from limits.aio.strategies import MovingWindowRateLimiter
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp

from voice_call_agent.http_hardening.error_responses import install_error_responses
from voice_call_agent.http_hardening.request_rate_limit import RequestRateLimitMiddleware
from voice_call_agent.http_hardening.security_headers import SecurityHeadersMiddleware
from voice_call_agent.settings.sections import HttpHardeningSettings, WebhookProtectionSettings


def harden_app(
    app: FastAPI,
    *,
    http: HttpHardeningSettings,
    webhooks: WebhookProtectionSettings,
    rate_limiter: MovingWindowRateLimiter,
    rate_limited_paths: frozenset[str],
    page_policies: Mapping[str, bytes] | None = None,
) -> ASGIApp:
    """Return the application wrapped for production use.

    Request order: security headers (outermost) → trusted host → body limit → rate limit →
    CORS (only when origins are configured) → routes. Starlette applies the middleware added
    last first, hence the reverse order of the calls below.
    """
    install_error_responses(app)
    if http.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(http.cors_allowed_origins),
            allow_methods=["GET", "POST"],
            allow_headers=[],
            allow_credentials=False,
        )
    app.add_middleware(
        RequestRateLimitMiddleware,
        limiter=rate_limiter,
        limit=webhooks.rate_limit,
        protected_paths=rate_limited_paths,
    )
    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=http.max_request_body_bytes)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(http.allowed_hosts))
    return SecurityHeadersMiddleware(
        app, strict_transport_security=http.is_production, page_policies=page_policies
    )
