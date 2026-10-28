"""The browser's WebRTC peer: answering its offer, waiting for it to connect, closing it."""

import asyncio
from typing import Literal

from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pydantic import BaseModel, ConfigDict, Field

from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode

CONNECT_TIMEOUT_SECONDS = 20.0
"""The browser runs on this machine, so ICE needs only host candidates. Shorter than Pipecat's own
connecting timeout (60 s), whose close leaves a later close hanging (manifest §10)."""
CLOSE_TIMEOUT_SECONDS = 5.0
_SETTLED_STATES = frozenset({"connected", "failed", "closed"})


class BrowserOffer(BaseModel):
    """The browser's SDP offer, with every ICE candidate already gathered (no trickle ICE)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sdp: str = Field(min_length=1, max_length=32_768)
    type: Literal["offer"]
    dialed_number: str | None = Field(default=None, max_length=16)
    """One of the practice lines (`GET /practice/lines`); without it the backend decides."""


class BrowserAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    sdp: str
    type: str


class UnanswerableOfferError(ValueError):
    """The offer has no audio section (aiortc would answer it and never connect), or Pipecat
    produced no answer."""


async def answer_offer(offer: BrowserOffer) -> tuple[SmallWebRTCConnection, BrowserAnswer]:
    """A peer connection for the offer, and the answer the browser applies."""
    if not _offers_audio(offer.sdp):
        raise UnanswerableOfferError
    # No ICE servers: the browser runs on this machine, so host candidates are enough.
    connection = SmallWebRTCConnection(ice_servers=None)
    try:
        await connection.initialize(sdp=offer.sdp, type=offer.type)
        # Pipecat's `SmallWebRTCConnection` methods carry no annotations.
        answer = connection.get_answer()  # type: ignore[no-untyped-call]
        if answer is None:
            raise UnanswerableOfferError
    except Exception:
        await close_peer(connection)
        raise
    return connection, BrowserAnswer(sdp=answer["sdp"], type=answer["type"])


async def wait_until_connected(connection: SmallWebRTCConnection, timeout_seconds: float) -> bool:
    """Whether the browser's peer connects within the timeout."""
    peer = connection.pc
    settled = asyncio.Event()

    def on_state_change() -> None:
        if peer.connectionState in _SETTLED_STATES:
            settled.set()

    peer.on("connectionstatechange", on_state_change)
    on_state_change()
    try:
        async with asyncio.timeout(timeout_seconds):
            await settled.wait()
    except TimeoutError:  # not an error: the caller reports a peer that never connected
        return False
    finally:
        peer.remove_listener("connectionstatechange", on_state_change)
    return peer.connectionState == "connected"


async def close_peer(connection: SmallWebRTCConnection) -> None:
    """Close the peer unless it is closed already, and never wait on it for long.

    After Pipecat's connecting timeout closes a peer, closing it again never returns; closing a peer
    that is still connecting sometimes does not return either (manifest §10).
    """
    if connection.pc.connectionState == "closed":
        return
    try:
        async with asyncio.timeout(CLOSE_TIMEOUT_SECONDS):
            # Pipecat's `SmallWebRTCConnection` methods carry no annotations.
            await connection.disconnect()  # type: ignore[no-untyped-call]
    except TimeoutError as error:
        report_error(ErrorCode.WEBRTC_CLOSE_TIMED_OUT, error=error)


def _offers_audio(sdp: str) -> bool:
    return any(line.startswith("m=audio ") for line in sdp.splitlines())
