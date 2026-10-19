from voice_call_agent.call_transports.twilio_media_streams.twiml_responses import (
    connect_stream_twiml,
    reject_busy_twiml,
)


def test_connect_stream_carries_url_and_parameters() -> None:
    twiml = connect_stream_twiml("wss://agent.example.com/twilio/stream", {"token": "1.abc"})
    assert '<Stream url="wss://agent.example.com/twilio/stream">' in twiml
    assert '<Parameter name="token" value="1.abc"' in twiml


def test_parameter_values_are_xml_escaped() -> None:
    twiml = connect_stream_twiml("wss://x/s", {"from": '"><Hangup/>'})
    assert "<Hangup/>" not in twiml


def test_reject_busy() -> None:
    assert '<Reject reason="busy"' in reject_busy_twiml()
