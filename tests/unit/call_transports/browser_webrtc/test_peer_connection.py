"""The browser's peer: a call whose browser never connects ends, and closing never hangs."""

import asyncio
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

from tests.browser_peer import browser_offer, reported_error_codes, wait_until
from tests.recording_doubles import RecordingConversationRunner
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.browser_webrtc import peer_connection
from voice_call_agent.call_transports.browser_webrtc.peer_connection import close_peer
from voice_call_agent.call_transports.browser_webrtc.practice_routes import build_practice_router


async def test_a_browser_that_never_connects_ends_the_call_and_frees_its_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Closing a peer that is still connecting sometimes does not finish (manifest §10).
    monkeypatch.setattr(peer_connection, "CLOSE_TIMEOUT_SECONDS", 1.0)
    supervisor = CallSupervisor(1)
    runner = RecordingConversationRunner()
    app = FastAPI()
    app.include_router(build_practice_router(supervisor, runner, None, connect_timeout_seconds=0.2))
    browser, offer = await browser_offer()  # Its answer is never applied: it never connects.
    try:
        with reported_error_codes() as codes:
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                assert (await client.post("/practice/offer", json=offer)).status_code == 200
            await wait_until(lambda: supervisor.active_calls == 0)
    finally:
        await browser.close()
    assert codes[0] == "PRACTICE_CALL_NOT_CONNECTED"
    assert set(codes[1:]) <= {"WEBRTC_CLOSE_TIMED_OUT"}
    assert runner.calls == []


async def test_a_peer_closed_by_pipecats_connecting_timeout_is_not_closed_again() -> None:
    browser, offer = await browser_offer()
    connection = SmallWebRTCConnection(connection_timeout_secs=1)
    try:
        await connection.initialize(sdp=offer["sdp"], type=offer["type"])
        await wait_until(lambda: connection.pc.connectionState == "closed")
        await close_peer(connection)  # Closing it again would never return.
    finally:
        await browser.close()


class _PeerThatNeverCloses:
    class _State:
        connectionState = "connecting"  # noqa: N815  # aiortc's attribute name

    pc = _State()

    async def disconnect(self) -> None:
        await asyncio.Event().wait()


async def test_a_close_that_never_finishes_is_reported_and_given_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peer_connection, "CLOSE_TIMEOUT_SECONDS", 0.05)
    with reported_error_codes() as codes:
        await close_peer(cast(SmallWebRTCConnection, _PeerThatNeverCloses()))
    assert codes == ["WEBRTC_CLOSE_TIMED_OUT"]
