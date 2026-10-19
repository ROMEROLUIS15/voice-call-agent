"""ASGI application: mounts the configured call entries over one speech engine."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Response, status
from fastapi.responses import JSONResponse
from loguru import logger

from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.twilio_media_streams.call_termination import (
    CallTerminator,
)
from voice_call_agent.call_transports.twilio_media_streams.webhook_routes import (
    build_twilio_router,
)
from voice_call_agent.call_transports.whatsapp_calling.call_acceptance import CallAcceptor
from voice_call_agent.call_transports.whatsapp_calling.webhook_routes import (
    build_whatsapp_router,
)
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
    shutdown_grace_seconds: float


def build_asgi_app(settings: ServiceSettings, components: ServiceComponents) -> FastAPI:
    """Create the application with the entries whose settings are complete."""
    supervisor = components.supervisor
    acceptor = components.call_acceptor

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if acceptor is not None:
            await acceptor.start()
        try:
            yield
        finally:
            # Under `GracefulHttpServer` the calls are already drained; under any other server
            # this is where they get their grace period.
            await supervisor.drain(components.shutdown_grace_seconds)
            if acceptor is not None:
                await acceptor.stop()

    app = FastAPI(title="Voice Call Agent", lifespan=lifespan)
    _add_health_routes(app, supervisor)

    twilio = settings.twilio_media_streams()
    if twilio is not None and components.call_terminator is not None:
        app.include_router(
            build_twilio_router(
                twilio, supervisor, components.conversation_runner, components.call_terminator
            )
        )
        logger.info("phone-line entry enabled")
    whatsapp = settings.whatsapp_calling()
    if whatsapp is not None and acceptor is not None:
        app.include_router(
            build_whatsapp_router(whatsapp, acceptor, supervisor, components.conversation_runner)
        )
        logger.info("WhatsApp entry enabled")
    if twilio is None and whatsapp is None:
        logger.warning("no call entry configured; check the phone-line and WhatsApp variables")
    return app


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
