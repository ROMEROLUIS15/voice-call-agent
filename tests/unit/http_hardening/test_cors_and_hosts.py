from fastapi.testclient import TestClient

from tests.unit.http_hardening.hardened_test_app import hardened_test_app

PANEL = "https://panel.example.com"
PREFLIGHT = {"Origin": PANEL, "Access-Control-Request-Method": "GET"}


def test_cors_is_closed_by_default() -> None:
    client = TestClient(hardened_test_app())
    assert "access-control-allow-origin" not in client.get("/ok", headers={"Origin": PANEL}).headers
    assert "access-control-allow-origin" not in client.options("/ok", headers=PREFLIGHT).headers


def test_cors_opens_only_to_configured_origins() -> None:
    client = TestClient(hardened_test_app(cors_allowed_origins=(PANEL,)))
    assert client.options("/ok", headers=PREFLIGHT).headers["access-control-allow-origin"] == PANEL
    other = {**PREFLIGHT, "Origin": "https://attacker.example.com"}
    assert "access-control-allow-origin" not in client.options("/ok", headers=other).headers


def test_unknown_host_is_refused() -> None:
    client = TestClient(hardened_test_app(), base_url="http://attacker.example.com")
    assert client.get("/ok").status_code == 400
