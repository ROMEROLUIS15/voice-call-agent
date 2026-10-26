import pytest
from fastapi.testclient import TestClient

from tests.unit.http_hardening.hardened_test_app import PAGE_PATH, PAGE_POLICY, hardened_test_app
from voice_call_agent.settings.sections import DeploymentEnvironment

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    "cache-control": "no-store",
}


@pytest.mark.parametrize("path", ["/ok", "/missing", "/fails", "/needs-param"])
def test_every_response_carries_the_security_headers(path: str) -> None:
    client = TestClient(hardened_test_app(), raise_server_exceptions=False)
    response = client.get(path)
    for name, value in EXPECTED.items():
        assert response.headers[name] == value, (path, name)


def test_hsts_only_in_production() -> None:
    production = TestClient(hardened_test_app()).get("/ok")
    development = TestClient(hardened_test_app(environment=DeploymentEnvironment.DEVELOPMENT)).get(
        "/ok"
    )
    assert production.headers["strict-transport-security"].startswith("max-age=")
    assert "strict-transport-security" not in development.headers


def test_application_cannot_weaken_or_reveal_headers() -> None:
    response = TestClient(hardened_test_app()).get("/sets-server-header")
    assert "server" not in response.headers
    assert response.headers.get_list("x-frame-options") == ["DENY"]


def test_a_page_gets_its_own_policy_and_keeps_the_other_headers() -> None:
    client = TestClient(hardened_test_app())
    page = client.get(PAGE_PATH)
    assert page.headers["content-security-policy"] == PAGE_POLICY.decode()
    assert page.headers["x-frame-options"] == "DENY"
    # Exact paths only: nothing under the page inherits its policy.
    nearby = client.get(PAGE_PATH + "/other")
    assert nearby.headers["content-security-policy"] == EXPECTED["content-security-policy"]
