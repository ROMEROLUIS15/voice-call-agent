"""Routes of the WhatsApp entry: webhook subscription and `calls` events."""

import hmac

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from loguru import logger

from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.whatsapp_calling.call_acceptance import CallAcceptor
from voice_call_agent.call_transports.whatsapp_calling.call_admission import admit_call_events
from voice_call_agent.call_transports.whatsapp_calling.calls_webhook_filter import (
    extract_call_events,
)
from voice_call_agent.call_transports.whatsapp_calling.webhook_signature import (
    is_valid_meta_signature,
)
from voice_call_agent.settings.sections import WhatsAppCallingSettings
from voice_call_agent.speech_pipeline.conversation_runner import ConversationRunner

WEBHOOK_PATH = "/whatsapp/webhook"


def build_whatsapp_router(
    settings: WhatsAppCallingSettings,
    acceptor: CallAcceptor,
    supervisor: CallSupervisor,
    conversation_runner: ConversationRunner,
) -> APIRouter:
    """Router of the WhatsApp entry."""
    router = APIRouter()
    app_secret = settings.app_secret.get_secret_value()
    verify_token = settings.verify_token.get_secret_value()

    @router.get(WEBHOOK_PATH)
    async def confirm_subscription(
        mode: str = Query(alias="hub.mode"),
        challenge: str = Query(alias="hub.challenge"),
        token: str = Query(alias="hub.verify_token"),
    ) -> Response:
        if mode != "subscribe" or not hmac.compare_digest(token, verify_token):
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        return PlainTextResponse(challenge)

    @router.post(WEBHOOK_PATH)
    async def receive_call_events(request: Request) -> Response:
        raw_body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")
        if not is_valid_meta_signature(app_secret, raw_body, signature):
            logger.warning("Meta webhook with an invalid signature")
            return Response(status_code=status.HTTP_401_UNAUTHORIZED)
        events = extract_call_events(raw_body)
        if events is None:
            return Response(status_code=status.HTTP_200_OK)
        try:
            await admit_call_events(
                events,
                acceptor=acceptor,
                supervisor=supervisor,
                conversation_runner=conversation_runner,
            )
        except Exception:
            # A connect event retried by Meta is useless (its SDP offer has expired): answer 200
            # anyway and keep the failure in the log (accepted trade-off, manifest §11).
            logger.exception("could not process the WhatsApp call event")
        return Response(status_code=status.HTTP_200_OK)

    return router
