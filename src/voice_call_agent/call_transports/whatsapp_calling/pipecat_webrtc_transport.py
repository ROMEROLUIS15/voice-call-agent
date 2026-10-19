"""Pipecat transport over an accepted WhatsApp WebRTC connection."""

from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from voice_call_agent.speech_pipeline.audio_format import AudioFormat

# WebRTC delivers Opus at 48 kHz; the pipeline runs at 16 kHz (STT) and 24 kHz (TTS).
WHATSAPP_AUDIO_FORMAT = AudioFormat(input_sample_rate_hz=16000, output_sample_rate_hz=24000)


def build_webrtc_transport(connection: SmallWebRTCConnection) -> SmallWebRTCTransport:
    """Transport of one call."""
    return SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(
            audio_in_enabled=True, audio_out_enabled=True, audio_out_10ms_chunks=2
        ),
    )
