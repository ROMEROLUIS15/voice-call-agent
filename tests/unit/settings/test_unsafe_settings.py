import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from tests.settings_factory import make_service_settings
from voice_call_agent.graceful_http_server import server_config


def test_cors_wildcard_is_rejected_at_startup() -> None:
    with pytest.raises(ValidationError, match="never"):
        make_service_settings(cors_allowed_origins="https://panel.example.com, *")


def test_invalid_rate_limit_is_rejected_at_startup() -> None:
    with pytest.raises(ValidationError, match="WEBHOOK_RATE_LIMIT"):
        make_service_settings(webhook_rate_limit="lots")


def test_public_host_is_always_allowed() -> None:
    hosts = make_service_settings(allowed_hosts="localhost").http_hardening().allowed_hosts
    assert hosts == ("localhost", "agent.example.com")


def test_production_is_the_default() -> None:
    assert make_service_settings().http_hardening().is_production


def test_uvicorn_never_announces_itself_and_trusts_only_configured_proxies() -> None:
    settings = make_service_settings(trusted_proxy_addresses="10.0.0.5")
    config = server_config(FastAPI(), settings.server(), settings.http_hardening())
    assert config.server_header is False
    assert config.forwarded_allow_ips == "10.0.0.5"
    assert config.ws_max_size == settings.http_hardening().max_websocket_message_bytes


def test_browser_practice_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="BROWSER_PRACTICE_ENABLED"):
        make_service_settings(browser_practice_enabled=True)


def test_browser_practice_is_off_by_default_and_allowed_in_development() -> None:
    assert not make_service_settings().browser_practice_enabled
    assert make_service_settings(
        browser_practice_enabled=True, environment="development"
    ).browser_practice_enabled


def test_the_practice_schedule_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="SCHEDULING_BACKEND"):
        make_service_settings(scheduling_backend="practice")
    assert (
        make_service_settings(
            scheduling_backend="practice", environment="development"
        ).scheduling_backend.value
        == "practice"
    )
