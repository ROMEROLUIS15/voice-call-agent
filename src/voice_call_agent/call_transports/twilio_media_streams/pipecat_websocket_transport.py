"""Pipecat transport over an open Twilio Media Stream WebSocket."""

from fastapi import WebSocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from voice_call_agent.call_transports.twilio_media_streams.stream_handshake import (
    StreamStartEvent,
)
from voice_call_agent.speech_pipeline.audio_format import AudioFormat

# μ-law at 8 kHz end to end: no resampling on input or output.
TWILIO_AUDIO_FORMAT = AudioFormat(input_sample_rate_hz=8000, output_sample_rate_hz=8000)


def build_media_stream_transport(
    websocket: WebSocket, start: StreamStartEvent
) -> FastAPIWebsocketTransport:
    """Transport of one call.

    Pipecat's automatic hang-up is off: it calls Twilio's REST API without an explicit timeout.
    The route ends the call itself through a `CallTerminator`.
    """
    serializer = TwilioFrameSerializer(
        stream_sid=start.stream_sid,
        call_sid=start.call_sid,
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )
    return FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
            # Twilio sends no `Origin`; the stream admission token authenticates the socket.
            allowed_origins=[],
        ),
    )
