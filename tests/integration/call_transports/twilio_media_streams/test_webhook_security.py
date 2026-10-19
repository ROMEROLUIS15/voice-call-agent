"""Negative security tests of the phone-line entry: every case fails closed."""

import json
import time

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from tests.app_builder import AppUnderTest
from tests.settings_factory import PUBLIC_BASE_URL, TWILIO_AUTH_TOKEN
from voice_call_agent.call_transports.twilio_media_streams.stream_admission_token import (
    derive_stream_token_key,
    issue_stream_token,
)

VOICE_URL = f"{PUBLIC_BASE_URL}/twilio/voice"
CALL = {"CallSid": "CA777", "From": "+584120000000", "To": "+13055550100"}


def _signed_headers(params: dict[str, str], delivery: str = "delivery-1") -> dict[str, str]:
    signature = str(RequestValidator(TWILIO_AUTH_TOKEN).compute_signature(VOICE_URL, params))
    return {"X-Twilio-Signature": signature, "I-Twilio-Idempotency-Token": delivery}


def _handshake(call_sid: str) -> list[str]:
    token = issue_stream_token(derive_stream_token_key(TWILIO_AUTH_TOKEN), call_sid, time.time())
    start = {
        "event": "start",
        "start": {"streamSid": "MZ1", "callSid": call_sid, "customParameters": {"token": token}},
    }
    return [json.dumps({"event": "connected"}), json.dumps(start)]


def test_missing_signature_is_refused() -> None:
    with TestClient(AppUnderTest().build()) as client:
        assert client.post("/twilio/voice", data=CALL).status_code == 403


def test_invalid_signature_is_refused() -> None:
    headers = {**_signed_headers(CALL), "X-Twilio-Signature": "forged"}
    with TestClient(AppUnderTest().build()) as client:
        assert client.post("/twilio/voice", data=CALL, headers=headers).status_code == 403


def test_altered_body_is_refused() -> None:
    headers = _signed_headers(CALL)
    altered = {**CALL, "From": "+15550009999"}
    with TestClient(AppUnderTest().build()) as client:
        assert client.post("/twilio/voice", data=altered, headers=headers).status_code == 403


def test_repeated_delivery_gets_no_new_stream_token() -> None:
    with TestClient(AppUnderTest().build()) as client:
        first = client.post("/twilio/voice", data=CALL, headers=_signed_headers(CALL))
        repeat = client.post("/twilio/voice", data=CALL, headers=_signed_headers(CALL))
    assert "<Stream" in first.text
    assert '<Reject reason="rejected"' in repeat.text
    assert "token" not in repeat.text


def test_second_stream_for_the_same_call_is_closed() -> None:
    app_under_test = AppUnderTest()
    with TestClient(app_under_test.build()) as client:
        with client.websocket_connect("/twilio/stream") as ws, pytest.raises(WebSocketDisconnect):
            for message in _handshake("CA777"):
                ws.send_text(message)
            ws.receive_text()
        with (
            client.websocket_connect("/twilio/stream") as ws,
            pytest.raises(WebSocketDisconnect) as closed,
        ):
            for message in _handshake("CA777"):
                ws.send_text(message)
            ws.receive_text()
    assert closed.value.code == 1008
    assert len(app_under_test.runner.calls) == 1


def test_webhook_flood_is_rate_limited_before_signature_checks() -> None:
    with TestClient(AppUnderTest().build(webhook_rate_limit="2/minute")) as client:
        statuses = [client.post("/twilio/voice", data=CALL).status_code for _ in range(3)]
    assert statuses == [403, 403, 429]


def test_stream_handshake_flood_is_refused() -> None:
    with TestClient(AppUnderTest().build(webhook_rate_limit="1/minute")) as client:
        with client.websocket_connect("/twilio/stream") as ws, pytest.raises(WebSocketDisconnect):
            ws.send_text("{}")
            ws.receive_text()
        with (
            pytest.raises(WebSocketDisconnect) as refused,
            client.websocket_connect("/twilio/stream"),
        ):
            pass
    assert refused.value.code == 1008


def test_oversized_webhook_body_is_refused() -> None:
    with TestClient(AppUnderTest().build(max_request_body_bytes=256)) as client:
        response = client.post("/twilio/voice", data={**CALL, "Padding": "x" * 1024})
    assert response.status_code == 413
