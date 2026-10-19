import json

from tests.whatsapp_payloads import connect_payload, messages_payload, terminate_payload
from voice_call_agent.call_transports.whatsapp_calling.calls_webhook_filter import (
    extract_call_events,
)


def test_connect_event_is_extracted() -> None:
    events = extract_call_events(json.dumps(connect_payload("wacid.1")).encode())
    assert events is not None
    assert [call.id for call in events.connect_calls] == ["wacid.1"]


def test_terminate_event_has_no_incoming_calls() -> None:
    events = extract_call_events(json.dumps(terminate_payload()).encode())
    assert events is not None
    assert events.connect_calls == []


def test_other_fields_are_ignored() -> None:
    assert extract_call_events(json.dumps(messages_payload()).encode()) is None


def test_calls_payload_pipecat_does_not_model_is_ignored() -> None:
    payload = connect_payload()
    payload["entry"][0]["changes"][0]["value"] = {"statuses": [{"id": "x"}]}
    assert extract_call_events(json.dumps(payload).encode()) is None


def test_unknown_shape_is_ignored() -> None:
    assert extract_call_events(b'{"hello": "world"}') is None
    assert extract_call_events(b"not json") is None
