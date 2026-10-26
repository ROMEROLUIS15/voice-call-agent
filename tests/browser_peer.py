"""A browser's side of a practice call, played by aiortc: the offer it sends and its peer."""

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from aiortc import RTCConfiguration, RTCPeerConnection
from loguru import logger

# Bounds every wait on a real peer connection, so a broken entry fails instead of hanging.
PEER_WAIT_SECONDS = 15.0


async def browser_offer() -> tuple[RTCPeerConnection, dict[str, str]]:
    """A peer like the practice page's: one audio transceiver and the keep-alive data channel.

    No ICE servers: like the page, it only needs host candidates on this machine.
    """
    peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    peer.addTransceiver("audio", direction="sendrecv")
    peer.createDataChannel("keep-alive")
    await peer.setLocalDescription(await peer.createOffer())
    return peer, {"sdp": peer.localDescription.sdp, "type": "offer"}


async def wait_until(condition: Callable[[], bool]) -> None:
    """Poll state that the code under test owns and signals with no event."""
    async with asyncio.timeout(PEER_WAIT_SECONDS):
        while not condition():  # noqa: ASYNC110  # no event to wait on
            await asyncio.sleep(0.05)


@contextmanager
def reported_error_codes() -> Iterator[list[str]]:
    """The error codes reported while the block runs."""
    codes: list[str] = []

    def keep_code(message: str) -> None:
        if code := json.loads(message)["record"]["extra"].get("error_code"):
            codes.append(code)

    sink_id = logger.add(keep_code, serialize=True, level="DEBUG")
    try:
        yield codes
    finally:
        logger.remove(sink_id)
