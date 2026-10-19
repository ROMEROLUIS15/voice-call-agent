"""Opening messages of a Twilio Media Stream."""

import asyncio

from fastapi import WebSocket
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# Twilio sends `connected` and then `start`; tolerate one extra message before them.
_MAX_HANDSHAKE_MESSAGES = 3


class StreamStartEvent(BaseModel):
    """Data of the Media Streams `start` event."""

    model_config = ConfigDict(populate_by_name=True)

    stream_sid: str = Field(alias="streamSid")
    call_sid: str = Field(alias="callSid")
    custom_parameters: dict[str, str] = Field(default_factory=dict, alias="customParameters")


class _Event(BaseModel):
    event: str


class _StartMessage(BaseModel):
    start: StreamStartEvent


class StreamHandshakeError(Exception):
    """The WebSocket did not deliver a valid `start` event in time."""


async def read_stream_start(websocket: WebSocket, timeout_seconds: float) -> StreamStartEvent:
    """Consume the stream's opening messages and return its `start` event."""
    try:
        async with asyncio.timeout(timeout_seconds):
            return await _read_until_start(websocket)
    except TimeoutError as error:
        raise StreamHandshakeError("no 'start' event before the handshake timeout") from error
    except ValidationError as error:
        raise StreamHandshakeError("malformed Media Stream message") from error


async def _read_until_start(websocket: WebSocket) -> StreamStartEvent:
    for _ in range(_MAX_HANDSHAKE_MESSAGES):
        raw = await websocket.receive_text()
        if _Event.model_validate_json(raw).event == "start":
            return _StartMessage.model_validate_json(raw).start
    raise StreamHandshakeError("the Media Stream sent no 'start' event")
