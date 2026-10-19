"""TwiML responses to an incoming call."""

from collections.abc import Mapping

from twilio.twiml.voice_response import Connect, VoiceResponse


def connect_stream_twiml(stream_url: str, parameters: Mapping[str, str]) -> str:
    """`<Connect><Stream>` with parameters Twilio forwards in the `start` event."""
    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=stream_url)
    for name, value in parameters.items():
        stream.parameter(name=name, value=value)
    response.append(connect)
    return str(response)


def reject_busy_twiml() -> str:
    """`<Reject reason="busy">`: Twilio does not answer the call and the caller hears busy."""
    response = VoiceResponse()
    response.reject(reason="busy")
    return str(response)
