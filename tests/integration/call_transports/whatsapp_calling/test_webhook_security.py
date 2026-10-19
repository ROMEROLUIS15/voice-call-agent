"""Negative security tests of the WhatsApp entry: every case fails closed."""

import json
import time

from fastapi.testclient import TestClient

from tests.app_builder import AppUnderTest
from tests.whatsapp_payloads import connect_payload, signed

WEBHOOK = "/whatsapp/webhook"


def _post(client: TestClient, body: bytes, signature: str | None) -> int:
    headers = {"X-Hub-Signature-256": signature} if signature else {}
    return client.post(WEBHOOK, content=body, headers=headers).status_code


def test_missing_signature_is_refused() -> None:
    app_under_test = AppUnderTest()
    body, _ = signed(connect_payload())
    with TestClient(app_under_test.build()) as client:
        assert _post(client, body, None) == 401
    assert app_under_test.acceptor.processed == []


def test_invalid_signature_is_refused() -> None:
    app_under_test = AppUnderTest()
    body, _ = signed(connect_payload())
    with TestClient(app_under_test.build()) as client:
        assert _post(client, body, "sha256=" + "0" * 64) == 401
    assert app_under_test.acceptor.processed == []


def test_altered_body_is_refused() -> None:
    app_under_test = AppUnderTest()
    payload = connect_payload()
    _, signature = signed(payload)
    payload["entry"][0]["changes"][0]["value"]["calls"][0]["from"] = "15550009999"
    with TestClient(app_under_test.build()) as client:
        assert _post(client, json.dumps(payload).encode(), signature) == 401
    assert app_under_test.acceptor.processed == []


def test_repeated_event_is_processed_once() -> None:
    app_under_test = AppUnderTest()
    body, signature = signed(connect_payload())
    with TestClient(app_under_test.build()) as client:
        assert _post(client, body, signature) == 200
        assert _post(client, body, signature) == 200  # Acknowledged, so Meta stops retrying.
    assert len(app_under_test.acceptor.processed) == 1


def test_stale_connect_is_not_processed() -> None:
    app_under_test = AppUnderTest()
    body, signature = signed(connect_payload(sent_at=time.time() - 3600))
    with TestClient(app_under_test.build()) as client:
        assert _post(client, body, signature) == 200
    assert app_under_test.acceptor.processed == []


def test_webhook_flood_is_rate_limited() -> None:
    with TestClient(AppUnderTest().build(webhook_rate_limit="2/minute")) as client:
        statuses = [client.post(WEBHOOK, content=b"{}").status_code for _ in range(3)]
    assert statuses == [401, 401, 429]
