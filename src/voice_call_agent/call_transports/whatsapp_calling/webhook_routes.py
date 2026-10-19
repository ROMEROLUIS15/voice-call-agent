"""Routes of the WhatsApp entry: webhook subscription and `calls` events."""

import hmac
import time

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import PlainTextResponse

from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.replay_guard import ReplayGuard
from voice_call_agent.call_transports.whatsapp_calling.call_acceptance import CallAcceptor
from voice_call_agent.call_transports.whatsapp_calling.call_admission import admit_call_events
from voice_call_agent.call_transports.whatsapp_calling.call_event_freshness import (
    delivery_rejection,
)
from voice_call_agent.call_transports.whatsapp_calling.calls_webhook_filter import (
    extract_call_events,
)
from voice_call_agent.call_transports.whatsapp_calling.webhook_signature import (
    is_valid_meta_signature,
)
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode
from voice_call_agent.settings.sections import WhatsAppCallingSettings
from voice_call_agent.speech_pipeline.conversation_runner import ConversationRunner

WEBHOOK_PATH = "/whatsapp/webhook"


def build_whatsapp_router(
    settings: WhatsAppCallingSettings,
    acceptor: CallAcceptor,
    supervisor: CallSupervisor,
    conversation_runner: ConversationRunner,
    replay_guard: ReplayGuard,
    max_connect_age_seconds: float,
) -> APIRouter:
    """Router of the WhatsApp entry."""
    endpoints = WhatsAppCallingEndpoints(
        settings, acceptor, supervisor, conversation_runner, replay_guard, max_connect_age_seconds
    )
    router = APIRouter()
    router.add_api_route(WEBHOOK_PATH, endpoints.confirm_subscription, methods=["GET"])
    router.add_api_route(WEBHOOK_PATH, endpoints.receive_call_events, methods=["POST"])
    return router


class WhatsAppCallingEndpoints:
    """The webhook subscription check and the `calls` events of the WhatsApp entry."""

    def __init__(
        self,
        settings: WhatsAppCallingSettings,
        acceptor: CallAcceptor,
        supervisor: CallSupervisor,
        conversation_runner: ConversationRunner,
        replay_guard: ReplayGuard,
        max_connect_age_seconds: float,
    ) -> None:
        self._app_secret = settings.app_secret.get_secret_value()
        self._verify_token = settings.verify_token.get_secret_value()
        self._acceptor = acceptor
        self._supervisor = supervisor
        self._conversation_runner = conversation_runner
        self._replay_guard = replay_guard
        self._max_connect_age_seconds = max_connect_age_seconds

    async def confirm_subscription(
        self,
        mode: str = Query(alias="hub.mode"),
        challenge: str = Query(alias="hub.challenge"),
        token: str = Query(alias="hub.verify_token"),
    ) -> Response:
        """Echo Meta's challenge when the verify token matches (compared in constant time)."""
        if mode != "subscribe" or not hmac.compare_digest(token, self._verify_token):
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        return PlainTextResponse(challenge)

    async def receive_call_events(self, request: Request) -> Response:
        """Validate, deduplicate and admit call events. Always `200` once the signature holds."""
        raw_body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")
        if not is_valid_meta_signature(self._app_secret, raw_body, signature):
            report_error(ErrorCode.WEBHOOK_SIGNATURE_INVALID, entry="whatsapp")
            return Response(status_code=status.HTTP_401_UNAUTHORIZED)
        events = extract_call_events(raw_body)
        if events is None:
            return Response(status_code=status.HTTP_200_OK)
        rejection = await delivery_rejection(
            events,
            replay_guard=self._replay_guard,
            now=time.time(),
            max_connect_age_seconds=self._max_connect_age_seconds,
        )
        if rejection is not None:
            # Fail closed: acknowledged so Meta stops delivering it, but never processed.
            report_error(rejection, entry="whatsapp")
            return Response(status_code=status.HTTP_200_OK)
        try:
            await admit_call_events(
                events,
                acceptor=self._acceptor,
                supervisor=self._supervisor,
                conversation_runner=self._conversation_runner,
            )
        except Exception as error:
            # A connect event retried by Meta is useless (its SDP offer has expired): answer 200
            # anyway and keep the failure in the log (accepted trade-off, manifest §11).
            report_error(ErrorCode.CALL_ADMISSION_FAILED, error=error)
        return Response(status_code=status.HTTP_200_OK)
