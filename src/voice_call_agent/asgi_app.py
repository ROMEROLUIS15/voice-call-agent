"""ASGI application: mounts the configured call entries over one speech engine."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Response, status
from fastapi.responses import JSONResponse
from limits.aio.strategies import MovingWindowRateLimiter
from loguru import logger
from starlette.types import ASGIApp

from voice_call_agent.call_session.business_resolution import BusinessResolver
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.browser_webrtc.practice_routes import (
    OFFER_PATH,
    PRACTICE_PAGE_PATH,
    PRACTICE_PAGE_POLICY,
    build_practice_router,
)
from voice_call_agent.call_transports.replay_guard import ReplayGuard
from voice_call_agent.call_transports.twilio_media_streams.call_termination import (
    CallTerminator,
)
from voice_call_agent.call_transports.twilio_media_streams.webhook_routes import (
    INCOMING_CALL_PATH,
    MEDIA_STREAM_PATH,
    build_twilio_router,
)
from voice_call_agent.call_transports.whatsapp_calling.call_acceptance import CallAcceptor
from voice_call_agent.call_transports.whatsapp_calling.webhook_routes import (
    WEBHOOK_PATH,
    build_whatsapp_router,
)
from voice_call_agent.http_hardening.app_hardening import harden_app
from voice_call_agent.settings.service_settings import ServiceSettings
from voice_call_agent.speech_pipeline.conversation_runner import ConversationRunner


@dataclass(frozen=True)
class ServiceComponents:
    """Dependencies of the application, built by `service_composition` (or by tests)."""

    supervisor: CallSupervisor
    conversation_runner: ConversationRunner
    call_terminator: CallTerminator | None
    """Present when the phone-line entry is configured."""
    call_acceptor: CallAcceptor | None
    """Present when the WhatsApp entry is configured."""
    replay_guard: ReplayGuard
    rate_limiter: MovingWindowRateLimiter
    shutdown_grace_seconds: float
    business_resolver: BusinessResolver | None = None
    """Present when a scheduling backend is configured; the practice entry resolves with it."""


def build_asgi_app(settings: ServiceSettings, components: ServiceComponents) -> ASGIApp:
    """Create the hardened application with the entries whose settings are complete."""
    http = settings.http_hardening()
    # No interactive documentation in production: it maps the attack surface for free.
    documented = not http.is_production
    app = FastAPI(
        title="Voice Call Agent",
        lifespan=_lifespan(components),
        docs_url="/docs" if documented else None,
        redoc_url="/redoc" if documented else None,
        openapi_url="/openapi.json" if documented else None,
    )
    _add_health_routes(app, components.supervisor)
    rate_limited_paths = _mount_call_entries(app, settings, components)
    page_policies: dict[str, bytes] = {}
    if settings.browser_practice_enabled:
        app.include_router(
            build_practice_router(
                components.supervisor, components.conversation_runner, components.business_resolver
            )
        )
        rate_limited_paths |= {OFFER_PATH}
        page_policies[PRACTICE_PAGE_PATH] = PRACTICE_PAGE_POLICY
        logger.warning("browser practice entry enabled: development only")
    return harden_app(
        app,
        http=http,
        webhooks=settings.webhook_protection(),
        rate_limiter=components.rate_limiter,
        rate_limited_paths=rate_limited_paths,
        page_policies=page_policies,
    )


def _lifespan(
    components: ServiceComponents,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        acceptor = components.call_acceptor
        if acceptor is not None:
            await acceptor.start()
        try:
            yield
        finally:
            # Under `GracefulHttpServer` the calls are already drained; under any other server
            # this is where they get their grace period.
            await components.supervisor.drain(components.shutdown_grace_seconds)
            if acceptor is not None:
                await acceptor.stop()

    return lifespan


def _mount_call_entries(
    app: FastAPI, settings: ServiceSettings, components: ServiceComponents
) -> frozenset[str]:
    """Mount the configured entries; return their paths, which are rate limited."""
    paths: set[str] = set()
    twilio = settings.twilio_media_streams()
    if twilio is not None and components.call_terminator is not None:
        app.include_router(
            build_twilio_router(
                twilio,
                components.supervisor,
                components.conversation_runner,
                components.call_terminator,
                components.replay_guard,
            )
        )
        paths |= {INCOMING_CALL_PATH, MEDIA_STREAM_PATH}
        logger.info("phone-line entry enabled")
    whatsapp = settings.whatsapp_calling()
    if whatsapp is not None and components.call_acceptor is not None:
        app.include_router(
            build_whatsapp_router(
                whatsapp,
                components.call_acceptor,
                components.supervisor,
                components.conversation_runner,
                components.replay_guard,
                settings.webhook_protection().connect_event_max_age_seconds,
            )
        )
        paths.add(WEBHOOK_PATH)
        logger.info("WhatsApp entry enabled")
    if not paths and not settings.browser_practice_enabled:
        logger.warning("no call entry configured; check the phone-line and WhatsApp variables")
    return frozenset(paths)


def _add_health_routes(app: FastAPI, supervisor: CallSupervisor) -> None:
    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> Response:
        """503 while draining or full, so load balancers send calls elsewhere."""
        if supervisor.can_accept_call():
            return JSONResponse({"status": "ready", "active_calls": supervisor.active_calls})
        reason = "draining" if supervisor.is_draining else "full"
        return JSONResponse(
            {"status": reason, "active_calls": supervisor.active_calls},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
