import pytest
from fastapi.testclient import TestClient

from tests.unit.http_hardening.hardened_test_app import LIMITED_PATH, hardened_test_app
from voice_call_agent.http_hardening.request_rate_limit import (
    RateLimitStorageError,
    build_rate_limiter,
)


def test_requests_beyond_the_limit_get_429_with_retry_after() -> None:
    client = TestClient(hardened_test_app(rate_limit="2/minute"))
    statuses = [client.get(LIMITED_PATH).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
    refused = client.get(LIMITED_PATH)
    assert int(refused.headers["retry-after"]) >= 1
    assert refused.json() == {"error": "too_many_requests"}


def test_limit_applies_per_route() -> None:
    client = TestClient(hardened_test_app(rate_limit="1/minute"))
    assert client.get(LIMITED_PATH).status_code == 200
    assert client.get(LIMITED_PATH).status_code == 429
    assert client.get("/ok").status_code == 200  # Not a protected route.


def test_synchronous_storage_is_rejected_at_startup() -> None:
    with pytest.raises(RateLimitStorageError):
        build_rate_limiter("memory://")
