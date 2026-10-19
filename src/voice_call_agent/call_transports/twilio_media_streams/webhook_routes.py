"""Routes of the phone-line entry: incoming-call webhook and Media Stream WebSocket."""

import time

from fastapi import APIRouter, Request, Response, WebSocket, status
from fastapi.websockets import WebSocketState
from loguru import logger

from voice_call_agent.call_session.session_builders import build_twilio_session
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.replay_guard import ReplayGuard
from voice_call_agent.call_transports.twilio_media_streams.call_termination import (
    CallTerminator,
)
from voice_call_agent.call_transports.twilio_media_streams.pipecat_websocket_transport import (
    TWILIO_AUDIO_FORMAT,
    build_media_stream_transport,
)
from voice_call_agent.call_transports.twilio_media_streams.request_signature import (
    is_valid_twilio_signature,
)
from voice_call_agent.call_transports.twilio_media_streams.stream_admission_token import (
    derive_stream_token_key,
    issue_stream_token,
    verify_stream_token,
)
from voice_call_agent.call_transports.twilio_media_streams.stream_handshake import (
    StreamHandshakeError,
    StreamStartEvent,
    read_stream_start,
)
from voice_call_agent.call_transports.twilio_media_streams.twiml_responses import (
    connect_stream_twiml,
    reject_busy_twiml,
    reject_call_twiml,
)
from voice_call_agent.settings.sections import TwilioMediaStreamsSettings
from voice_call_agent.speech_pipeline.conversation_runner import ConversationRunner

INCOMING_CALL_PATH = "/twilio/voice"
MEDIA_STREAM_PATH = "/twilio/stream"
_TRY_AGAIN_LATER = 1013
# Twilio sends it on every webhook; a retry of the same delivery repeats it.
_DELIVERY_ID_HEADER = "I-Twilio-Idempotency-Token"


def build_twilio_router(
    settings: TwilioMediaStreamsSettings,
    supervisor: CallSupervisor,
    conversation_runner: ConversationRunner,
    call_terminator: CallTerminator,
    replay_guard: ReplayGuard,
) -> APIRouter:
    """Router of the phone-line entry."""
    endpoints = TwilioMediaStreamsEndpoints(
        settings, supervisor, conversation_runner, call_terminator, replay_guard
    )
    router = APIRouter()
    router.add_api_route(INCOMING_CALL_PATH, endpoints.answer_incoming_call, methods=["POST"])
    router.add_api_websocket_route(MEDIA_STREAM_PATH, endpoints.serve_media_stream)
    return router


class TwilioMediaStreamsEndpoints:
    """The two endpoints of a phone-line call: the signed webhook and its Media Stream."""

    def __init__(
        self,
        settings: TwilioMediaStreamsSettings,
        supervisor: CallSupervisor,
        conversation_runner: ConversationRunner,
        call_terminator: CallTerminator,
        replay_guard: ReplayGuard,
    ) -> None:
        self._settings = settings
        self._replay_guard = replay_guard
        self._supervisor = supervisor
        self._conversation_runner = conversation_runner
        self._call_terminator = call_terminator
        self._auth_token = settings.auth_token.get_secret_value()
        self._token_key = derive_stream_token_key(self._auth_token)
        self._base_url = str(settings.public_base_url).rstrip("/")

    async def answer_incoming_call(self, request: Request) -> Response:
        """Validate the webhook and connect the call to a Media Stream (or reject it as busy)."""
        form = await request.form()
        params = {key: value for key, value in form.items() if isinstance(value, str)}
        query = f"?{request.url.query}" if request.url.query else ""
        signature = request.headers.get("X-Twilio-Signature")
        url = self._base_url + INCOMING_CALL_PATH + query
        if not is_valid_twilio_signature(self._auth_token, url, params, signature):
            logger.warning("Twilio webhook with an invalid signature")
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        call_sid = params.get("CallSid")
        if not call_sid:
            return Response(status_code=status.HTTP_400_BAD_REQUEST)
        delivery_id = request.headers.get(_DELIVERY_ID_HEADER) or call_sid
        if not await self._replay_guard.first_seen(f"twilio-voice:{delivery_id}"):
            # Fail closed: a repeated delivery never gets a fresh stream admission token.
            logger.bind(call_id=call_sid).warning("repeated Twilio webhook delivery rejected")
            return Response(content=reject_call_twiml(), media_type="application/xml")
        if not self._supervisor.can_accept_call():
            logger.bind(call_id=call_sid).warning("instance full; rejecting call as busy")
            return Response(content=reject_busy_twiml(), media_type="application/xml")
        twiml = connect_stream_twiml(
            _to_websocket_url(self._base_url) + MEDIA_STREAM_PATH,
            {
                "token": issue_stream_token(self._token_key, call_sid, time.time()),
                "from": params.get("From", ""),
                "to": params.get("To", ""),
            },
        )
        return Response(content=twiml, media_type="application/xml")

    async def serve_media_stream(self, websocket: WebSocket) -> None:
        """Run the call over its Media Stream once it is admitted and a call slot is held."""
        await websocket.accept()
        start = await _admit_stream(
            websocket,
            self._token_key,
            self._settings.handshake_timeout_seconds,
            self._replay_guard,
        )
        if start is None:
            return
        # The webhook only checked for a free slot; it is taken when the media actually arrives.
        slot = self._supervisor.try_reserve()
        if slot is None:
            await websocket.close(code=_TRY_AGAIN_LATER)
            return
        params = start.custom_parameters
        session = build_twilio_session(start.call_sid, params.get("from"), params.get("to"))
        transport = build_media_stream_transport(websocket, start)
        try:
            await self._supervisor.run_in_current_task(
                slot, self._conversation_runner.run(transport, session, TWILIO_AUDIO_FORMAT)
            )
        finally:
            await _finish_stream(websocket, self._call_terminator, start.call_sid)


async def _admit_stream(
    websocket: WebSocket,
    token_key: bytes,
    handshake_timeout_seconds: float,
    replay_guard: ReplayGuard,
) -> StreamStartEvent | None:
    """The stream's `start` event if it is admitted; otherwise the socket is closed.

    Admitted means a valid admission token and the first stream of that call: a token replayed
    within its validity cannot open a second conversation.
    """
    try:
        start = await read_stream_start(websocket, handshake_timeout_seconds)
    except StreamHandshakeError as error:
        logger.bind(reason=str(error)).warning("Media Stream rejected")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    token = start.custom_parameters.get("token")
    if not verify_stream_token(token_key, start.call_sid, token, time.time()):
        logger.bind(call_id=start.call_sid).warning("Media Stream with an invalid admission token")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    if not await replay_guard.first_seen(f"twilio-stream:{start.call_sid}"):
        logger.bind(call_id=start.call_sid).warning(
            "second Media Stream for the same call rejected"
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    return start


async def _finish_stream(websocket: WebSocket, terminator: CallTerminator, call_sid: str) -> None:
    """End the call if the caller is still on the line, then make sure the socket is closed."""
    if websocket.client_state is not WebSocketState.CONNECTED:
        return  # The caller hung up: Twilio already ended the call and closed the socket.
    await terminator.end_call(call_sid)
    if websocket.application_state is WebSocketState.CONNECTED:
        await websocket.close()


def _to_websocket_url(base_url: str) -> str:
    """`https://host` → `wss://host`. Twilio only accepts `wss://` outside local tests."""
    scheme, rest = base_url.split("://", 1)
    return ("wss" if scheme == "https" else "ws") + "://" + rest
