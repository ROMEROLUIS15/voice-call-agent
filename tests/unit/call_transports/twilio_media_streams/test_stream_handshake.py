import asyncio
import json
from typing import cast

import pytest
from fastapi import WebSocket

from voice_call_agent.call_transports.twilio_media_streams.stream_handshake import (
    StreamHandshakeError,
    read_stream_start,
)

START = {
    "event": "start",
    "start": {
        "streamSid": "MZ1",
        "callSid": "CA1",
        "customParameters": {"token": "t"},
    },
}


class ScriptedWebSocket:
    """Delivers the given messages, then waits forever like a silent peer."""

    def __init__(self, *messages: str) -> None:
        self._messages = list(messages)

    async def receive_text(self) -> str:
        if self._messages:
            return self._messages.pop(0)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def _socket(*messages: str) -> WebSocket:
    return cast(WebSocket, ScriptedWebSocket(*messages))


async def test_start_event_follows_connected() -> None:
    socket = _socket(json.dumps({"event": "connected"}), json.dumps(START))
    start = await read_stream_start(socket, timeout_seconds=1)
    assert (start.call_sid, start.stream_sid) == ("CA1", "MZ1")
    assert start.custom_parameters == {"token": "t"}


async def test_silent_peer_times_out() -> None:
    # The outer bound turns a missing handshake timeout into a failure instead of a hang.
    with pytest.raises(StreamHandshakeError, match="timeout"):
        await asyncio.wait_for(read_stream_start(_socket(), timeout_seconds=0.05), timeout=2)


async def test_stream_without_start_is_rejected() -> None:
    socket = _socket(*[json.dumps({"event": "media"})] * 3)
    with pytest.raises(StreamHandshakeError):
        await read_stream_start(socket, timeout_seconds=1)


async def test_malformed_message_is_rejected() -> None:
    with pytest.raises(StreamHandshakeError, match="malformed"):
        await read_stream_start(_socket("not json"), timeout_seconds=1)
