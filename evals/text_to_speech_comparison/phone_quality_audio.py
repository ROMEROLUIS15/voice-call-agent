"""Audio as a caller hears it on the phone line: μ-law at 8 kHz, saved as a playable WAV."""

import io
import wave

from pipecat.audio.utils import create_stream_resampler, pcm_to_ulaw, ulaw_to_pcm

_BYTES_PER_SAMPLE = 2


async def phone_line_wav(pcm: bytes, sample_rate_hz: int) -> bytes:
    """The 16-bit PCM through the μ-law round trip of the Twilio serializer, as a WAV file."""
    ulaw = await pcm_to_ulaw(pcm, sample_rate_hz, sample_rate_hz, create_stream_resampler())
    heard = await ulaw_to_pcm(ulaw, sample_rate_hz, sample_rate_hz, create_stream_resampler())
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(_BYTES_PER_SAMPLE)
        wav.setframerate(sample_rate_hz)
        wav.writeframes(heard)
    return buffer.getvalue()
