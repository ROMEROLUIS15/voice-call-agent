"""The HTTP surface of the real application: documentation, headers and hosts."""

from fastapi.testclient import TestClient

from tests.app_builder import AppUnderTest


def test_interactive_docs_are_off_in_production() -> None:
    with TestClient(AppUnderTest().build()) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404, path


def test_interactive_docs_are_on_in_development() -> None:
    with TestClient(AppUnderTest().build(environment="development")) as client:
        assert client.get("/openapi.json").status_code == 200


def test_health_responses_carry_security_headers() -> None:
    with TestClient(AppUnderTest().build()) as client:
        response = client.get("/health/live")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["strict-transport-security"].startswith("max-age=")


def test_requests_for_another_host_are_refused() -> None:
    app = AppUnderTest().build()
    with TestClient(app, base_url="http://attacker.example.com") as client:
        assert client.get("/health/live").status_code == 400
