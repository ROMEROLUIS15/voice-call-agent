from fastapi.testclient import TestClient

from tests.app_builder import AppUnderTest
from tests.settings_factory import META_VERIFY_TOKEN
from tests.whatsapp_payloads import connect_payload, messages_payload, signed

WEBHOOK = "/whatsapp/webhook"


def test_subscription_echoes_the_challenge() -> None:
    params = {"hub.mode": "subscribe", "hub.challenge": "42", "hub.verify_token": META_VERIFY_TOKEN}
    with TestClient(AppUnderTest().build()) as client:
        response = client.get(WEBHOOK, params=params)
    assert response.status_code == 200
    assert response.text == "42"


def test_subscription_with_a_wrong_token_is_rejected() -> None:
    params = {"hub.mode": "subscribe", "hub.challenge": "42", "hub.verify_token": "nope"}
    with TestClient(AppUnderTest().build()) as client:
        assert client.get(WEBHOOK, params=params).status_code == 403


def test_event_signed_with_another_secret_is_rejected() -> None:
    app_under_test = AppUnderTest()
    body, header = signed(connect_payload(), secret="attacker")
    with TestClient(app_under_test.build()) as client:
        response = client.post(WEBHOOK, content=body, headers={"X-Hub-Signature-256": header})
    assert response.status_code == 401
    assert app_under_test.acceptor.processed == []


def test_connect_event_reaches_the_acceptor() -> None:
    app_under_test = AppUnderTest()
    body, header = signed(connect_payload())
    with TestClient(app_under_test.build()) as client:
        response = client.post(WEBHOOK, content=body, headers={"X-Hub-Signature-256": header})
    assert response.status_code == 200
    [webhook] = app_under_test.acceptor.processed
    assert webhook.entry[0].changes[0].value.calls[0].id == "wacid.ABC"


def test_other_fields_are_acknowledged_and_ignored() -> None:
    app_under_test = AppUnderTest()
    body, header = signed(messages_payload())
    with TestClient(app_under_test.build()) as client:
        response = client.post(WEBHOOK, content=body, headers={"X-Hub-Signature-256": header})
    assert response.status_code == 200
    assert app_under_test.acceptor.processed == []
