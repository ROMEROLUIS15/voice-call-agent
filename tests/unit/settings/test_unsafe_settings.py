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


def test_conversation_transcripts_are_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="CONVERSATION_TRANSCRIPTS_DIR"):
        make_service_settings(conversation_transcripts_dir="var/conversation_transcripts")
    assert make_service_settings().conversation_transcripts() is None
    transcripts = make_service_settings(
        conversation_transcripts_dir="var/conversation_transcripts", environment="development"
    ).conversation_transcripts()
    assert transcripts is not None
    assert transcripts.directory.name == "conversation_transcripts"


def test_the_log_file_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="LOG_FILE_PATH"):
        make_service_settings(log_file_path="var/service.log")
    log = make_service_settings(
        log_file_path="var/service.log", environment="development"
    ).logging_output()
    assert log.file_path is not None and log.file_level == "DEBUG"


def test_the_scheduling_api_needs_its_url_and_secret_and_https_in_production() -> None:
    with pytest.raises(
        ValidationError, match="SCHEDULING_API_URL and SCHEDULING_API_SIGNING_SECRET"
    ):
        make_service_settings(
            scheduling_backend="api", scheduling_api_url="https://api.example.com/fn"
        )
    with pytest.raises(ValidationError, match="https"):
        make_service_settings(
            scheduling_backend="api",
            scheduling_api_url="http://127.0.0.1:54321/functions/v1/phone-agent-api",
            scheduling_api_signing_secret="s3cret",
        )
    api = make_service_settings(
        scheduling_backend="api",
        scheduling_api_url="http://127.0.0.1:54321/functions/v1/phone-agent-api/",
        scheduling_api_signing_secret="s3cret",
        environment="development",
    ).scheduling_api()
    assert api is not None and api.base_url.endswith("/phone-agent-api")
    assert "s3cret" not in repr(api)  # A SecretStr: never printed.
    assert make_service_settings().scheduling_api() is None


def test_practice_lines_take_only_fictitious_numbers() -> None:
    settings = make_service_settings(
        practice_lines="+13055550101=Barbería Local; +13055550102=Clínica"
    )
    assert settings.practice_lines.startswith("+13055550101")
    for spec in ("+584121234567=Real", "+13055550101", "+13055550101=A=B"):
        with pytest.raises(ValidationError, match="PRACTICE_LINES"):
            make_service_settings(practice_lines=spec)  # A real number never reaches the page.
