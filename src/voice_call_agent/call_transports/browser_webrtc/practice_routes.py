"""Routes of the browser practice entry: the practice page, its script and the WebRTC offer."""

import ipaddress
import uuid
from importlib import resources

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

from voice_call_agent.call_session.business_resolution import BusinessResolved, BusinessResolver
from voice_call_agent.call_session.session import CallSession
from voice_call_agent.call_session.session_builders import build_browser_session
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.browser_webrtc.peer_connection import (
    CONNECT_TIMEOUT_SECONDS,
    BrowserOffer,
    answer_offer,
    close_peer,
    wait_until_connected,
)
from voice_call_agent.call_transports.pipecat_webrtc_transport import (
    WEBRTC_AUDIO_FORMAT,
    build_webrtc_transport,
)
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendError,
    SchedulingBackendUnavailableError,
)
from voice_call_agent.speech_pipeline.conversation_runner import ConversationRunner

PRACTICE_PAGE_PATH = "/practice"
PRACTICE_SCRIPT_PATH = "/practice/call.js"
OFFER_PATH = "/practice/offer"
PRACTICE_PAGE_POLICY = (
    b"default-src 'none'; script-src 'self'; connect-src 'self'; "
    b"base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
"""The page loads its own script and posts its offer to this service; nothing else."""


def build_practice_router(
    supervisor: CallSupervisor,
    conversation_runner: ConversationRunner,
    business_resolver: BusinessResolver | None,
    connect_timeout_seconds: float = CONNECT_TIMEOUT_SECONDS,
) -> APIRouter:
    """Router of the practice entry. Reads the page once, at startup."""
    page = resources.files(__package__) / "practice_page"
    endpoints = BrowserPracticeEndpoints(
        supervisor,
        conversation_runner,
        business_resolver,
        page=(page / "index.html").read_text(encoding="utf-8"),
        script=(page / "call.js").read_text(encoding="utf-8"),
        connect_timeout_seconds=connect_timeout_seconds,
    )
    router = APIRouter()
    router.add_api_route(PRACTICE_PAGE_PATH, endpoints.practice_page, methods=["GET"])
    router.add_api_route(PRACTICE_SCRIPT_PATH, endpoints.practice_script, methods=["GET"])
    router.add_api_route(OFFER_PATH, endpoints.receive_offer, methods=["POST"])
    return router


class BrowserPracticeEndpoints:
    """The practice page and the offer that starts a call from it."""

    def __init__(
        self,
        supervisor: CallSupervisor,
        conversation_runner: ConversationRunner,
        business_resolver: BusinessResolver | None,
        *,
        page: str,
        script: str,
        connect_timeout_seconds: float,
    ) -> None:
        self._supervisor = supervisor
        self._conversation_runner = conversation_runner
        self._business_resolver = business_resolver
        self._page = page
        self._script = script
        self._connect_timeout_seconds = connect_timeout_seconds

    async def practice_page(self) -> Response:
        return HTMLResponse(self._page)

    async def practice_script(self) -> Response:
        return Response(self._script, media_type="text/javascript")

    async def receive_offer(self, offer: BrowserOffer, request: Request) -> Response:
        """Answer the offer of a browser on this machine and start the call."""
        if not _is_loopback(request.client.host if request.client else None):
            report_error(ErrorCode.PRACTICE_CLIENT_NOT_LOCAL, entry="browser")
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        slot = self._supervisor.try_reserve()
        if slot is None:
            report_error(ErrorCode.CALL_REJECTED_NO_SLOT, entry="browser")
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            connection, answer = await answer_offer(offer)
        except ValueError as error:
            slot.release()
            report_error(ErrorCode.REQUEST_INVALID, error=error, entry="browser")
            return Response(status_code=status.HTTP_400_BAD_REQUEST)
        except BaseException:
            slot.release()
            raise
        session = build_browser_session(f"practice-{uuid.uuid4().hex}")
        self._supervisor.launch(slot, self._converse(connection, session))
        return JSONResponse(answer.model_dump())

    async def _converse(self, connection: SmallWebRTCConnection, session: CallSession) -> None:
        """Hold the call once the browser connects, then close its peer."""
        try:
            if not await wait_until_connected(connection, self._connect_timeout_seconds):
                report_error(ErrorCode.PRACTICE_CALL_NOT_CONNECTED, call_id=session.call_id)
                return
            session = await self._with_business(session)
            transport = build_webrtc_transport(connection)
            await self._conversation_runner.run(transport, session, WEBRTC_AUDIO_FORMAT)
        finally:
            await close_peer(connection)

    async def _with_business(self, session: CallSession) -> CallSession:
        """The session with the business the backend resolves for it, when there is a backend.

        The call has no dialed number, so the backend decides (the practice schedule picks its
        default business). Unresolved, the call goes on without a business and nothing can be
        written (constitution §3).
        """
        if self._business_resolver is None:
            return session
        try:
            resolution = await self._business_resolver.resolve_call_business(session)
        except SchedulingBackendError as error:
            code = (
                ErrorCode.SCHEDULING_BACKEND_UNAVAILABLE
                if isinstance(error, SchedulingBackendUnavailableError)
                else ErrorCode.SCHEDULING_BACKEND_REJECTED
            )
            report_error(code, error=error, call_id=session.call_id)
            return session
        if isinstance(resolution, BusinessResolved):
            return session.resolve_business(resolution.business_id, resolution.context)
        return session


def _is_loopback(host: str | None) -> bool:
    """Whether the client address is this machine's.

    A local tunnel that sends `X-Forwarded-For` does not pass for local: uvicorn trusts the proxy
    headers of `TRUSTED_PROXY_ADDRESSES` (`127.0.0.1` by default) and puts the forwarded client
    here. One that strips the header would, which is one reason the entry is development only.
    """
    if host is None:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:  # not an error: a host name, never a loopback address here
        return False
