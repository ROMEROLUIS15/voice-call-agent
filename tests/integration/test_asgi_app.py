from fastapi.testclient import TestClient

from tests.app_builder import AppUnderTest
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor


def test_lifespan_starts_and_stops_the_call_acceptor() -> None:
    app_under_test = AppUnderTest()
    with TestClient(app_under_test.build()):
        assert app_under_test.acceptor.started
    assert app_under_test.acceptor.stopped


def test_liveness() -> None:
    with TestClient(AppUnderTest().build()) as client:
        assert client.get("/health/live").json() == {"status": "ok"}


def test_ready_while_a_call_slot_is_free() -> None:
    with TestClient(AppUnderTest().build()) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200


def test_not_ready_when_full() -> None:
    app_under_test = AppUnderTest(supervisor=CallSupervisor(max_concurrent_calls=1))
    app_under_test.supervisor.try_reserve()
    with TestClient(app_under_test.build()) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "full"


def test_disabled_entries_have_no_routes() -> None:
    app = AppUnderTest().build(
        public_base_url=None,
        twilio_account_sid=None,
        twilio_auth_token=None,
        whatsapp_access_token=None,
        whatsapp_phone_number_id=None,
        whatsapp_app_secret=None,
        whatsapp_verify_token=None,
    )
    with TestClient(app) as client:
        assert client.post("/twilio/voice").status_code == 404
        assert client.post("/whatsapp/webhook").status_code == 404
