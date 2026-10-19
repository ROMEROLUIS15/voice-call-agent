import json
import time

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from tests.app_builder import AppUnderTest
from tests.settings_factory import PUBLIC_BASE_URL, TWILIO_AUTH_TOKEN
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.twilio_media_streams.pipecat_websocket_transport import (
    TWILIO_AUDIO_FORMAT,
)
from voice_call_agent.call_transports.twilio_media_streams.stream_admission_token import (
    derive_stream_token_key,
    issue_stream_token,
)

VOICE_URL = f"{PUBLIC_BASE_URL}/twilio/voice"
CALL = {"CallSid": "CA123", "From": "+584121234567", "To": "+13055550100"}


@pytest.fixture
def app_under_test() -> AppUnderTest:
    return AppUnderTest()


def _sign(params: dict[str, str]) -> str:
    return str(RequestValidator(TWILIO_AUTH_TOKEN).compute_signature(VOICE_URL, params))


def _valid_token() -> str:
    return issue_stream_token(
        derive_stream_token_key(TWILIO_AUTH_TOKEN), CALL["CallSid"], time.time()
    )


def _handshake(token: str) -> list[str]:
    start = {
        "event": "start",
        "start": {
            "accountSid": "AC0",
            "streamSid": "MZ1",
            "callSid": CALL["CallSid"],
            "tracks": ["inbound"],
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            "customParameters": {"token": token, "from": CALL["From"], "to": CALL["To"]},
        },
        "streamSid": "MZ1",
    }
    return [json.dumps({"event": "connected", "protocol": "Call"}), json.dumps(start)]


def test_incoming_call_returns_stream_twiml(app_under_test: AppUnderTest) -> None:
    with TestClient(app_under_test.build()) as client:
        response = client.post(
            "/twilio/voice", data=CALL, headers={"X-Twilio-Signature": _sign(CALL)}
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert '<Stream url="wss://agent.example.com/twilio/stream">' in response.text
    assert '<Parameter name="token"' in response.text


@pytest.mark.parametrize(
    "signature",
    [None, "bad-signature", _sign({**CALL, "To": "+19999999999"})],
    ids=["missing", "invalid", "other-params"],
)
def test_incoming_call_with_a_bad_signature_is_rejected(
    app_under_test: AppUnderTest, signature: str | None
) -> None:
    headers = {"X-Twilio-Signature": signature} if signature else {}
    with TestClient(app_under_test.build()) as client:
        response = client.post("/twilio/voice", data=CALL, headers=headers)
    assert response.status_code == 403


def test_incoming_call_when_full_is_rejected_as_busy() -> None:
    app_under_test = AppUnderTest(supervisor=CallSupervisor(max_concurrent_calls=1))
    app_under_test.supervisor.try_reserve()
    with TestClient(app_under_test.build()) as client:
        response = client.post(
            "/twilio/voice", data=CALL, headers={"X-Twilio-Signature": _sign(CALL)}
        )
    assert '<Reject reason="busy"' in response.text


def test_stream_with_a_valid_token_runs_the_call(app_under_test: AppUnderTest) -> None:
    with (
        TestClient(app_under_test.build()) as client,
        client.websocket_connect("/twilio/stream") as ws,
        pytest.raises(WebSocketDisconnect),
    ):
        for message in _handshake(_valid_token()):
            ws.send_text(message)
        ws.receive_text()  # The server closes the socket once the conversation ends.

    [(session, audio_format)] = app_under_test.runner.calls
    assert session.call_id == "CA123"
    assert session.caller_phone == "+584121234567"
    assert not session.identity_verified
    assert audio_format == TWILIO_AUDIO_FORMAT
    assert app_under_test.terminator.ended == ["CA123"]  # The caller was still on the line.
    assert app_under_test.supervisor.active_calls == 0


def test_stream_with_a_forged_token_is_closed(app_under_test: AppUnderTest) -> None:
    with (
        TestClient(app_under_test.build()) as client,
        client.websocket_connect("/twilio/stream") as ws,
        pytest.raises(WebSocketDisconnect) as closed,
    ):
        for message in _handshake("9999999999.forged"):
            ws.send_text(message)
        ws.receive_text()
    assert closed.value.code == 1008
    assert app_under_test.runner.calls == []


def test_stream_beyond_the_limit_is_closed() -> None:
    app_under_test = AppUnderTest(supervisor=CallSupervisor(max_concurrent_calls=1))
    app_under_test.supervisor.try_reserve()
    with (
        TestClient(app_under_test.build()) as client,
        client.websocket_connect("/twilio/stream") as ws,
        pytest.raises(WebSocketDisconnect) as closed,
    ):
        for message in _handshake(_valid_token()):
            ws.send_text(message)
        ws.receive_text()
    assert closed.value.code == 1013
    assert app_under_test.runner.calls == []
