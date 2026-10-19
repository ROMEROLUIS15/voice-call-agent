from fastapi.testclient import TestClient

from tests.unit.http_hardening.hardened_test_app import LEAKY_ERROR, hardened_test_app


def test_unexpected_error_reveals_nothing() -> None:
    response = TestClient(hardened_test_app(), raise_server_exceptions=False).get("/fails")
    assert response.status_code == 500
    assert response.json() == {"error": "internal_server_error"}
    assert LEAKY_ERROR not in response.text
    for leak in ("hunter2", "/srv/app", "Traceback", "RuntimeError"):
        assert leak not in response.text


def test_validation_error_does_not_echo_the_input() -> None:
    response = TestClient(hardened_test_app()).get(
        "/needs-param", params={"count": "secret-looking-input"}
    )
    assert response.status_code == 422
    assert "secret-looking-input" not in response.text
    assert set(response.json()) == {"error"}


def test_not_found_has_a_generic_body() -> None:
    response = TestClient(hardened_test_app()).get("/internal/admin")
    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


def test_request_body_beyond_the_limit_is_refused() -> None:
    response = TestClient(hardened_test_app(max_request_body_bytes=64)).post(
        "/echo", json={"padding": "x" * 200}
    )
    assert response.status_code == 413
