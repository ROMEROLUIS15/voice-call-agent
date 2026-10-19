from typing import cast

import sentry_sdk
from loguru import logger
from pydantic import SecretStr
from sentry_sdk.types import Event

from tests.sentry_capture import CapturingTransport
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode
from voice_call_agent.observability.error_tracking import configure_error_tracking, scrub_event
from voice_call_agent.settings.sections import DeploymentEnvironment, ErrorTrackingSettings


def test_without_a_dsn_nothing_is_initialized() -> None:
    settings = ErrorTrackingSettings(
        dsn=None, environment=DeploymentEnvironment.PRODUCTION, release="x", traces_sample_rate=1
    )
    assert configure_error_tracking(settings) is False


def test_scrub_removes_request_and_user_and_redacts_phones() -> None:
    event = cast(
        Event,
        {
            "message": "call from +58 412 000 0000 failed",
            "request": {"headers": {"X-Twilio-Signature": "abc"}, "data": "From=%2B584120000000"},
            "user": {"ip_address": "203.0.113.7"},
            "extra": {"nested": ["caller +584120000000"]},
        },
    )
    scrubbed = scrub_event(event, {})
    assert "request" not in scrubbed
    assert "user" not in scrubbed
    assert "0000000" not in str(scrubbed)
    assert "+58" in str(scrubbed)  # The redacted form keeps the country code.


def test_configured_client_scrubs_what_it_sends(sentry_capture: CapturingTransport) -> None:
    sentry_sdk.capture_message("caller +584120000000 hung up")
    [event] = sentry_capture.items("event")
    assert "+584120000000" not in str(event)
    assert event["environment"] == "development"
    assert event["release"] == "voice-call-agent@test"


RUNTIME_SECRET = "-".join(["sk", "runtime", "secret"])
"""Built at run time, as a key read from the environment: absent from the source lines."""


def _failing_provider_call() -> None:
    api_key = RUNTIME_SECRET  # A secret in a local variable of the failing frame.
    raise RuntimeError(f"provider refused a key of {len(api_key)} characters")


def test_stack_frames_carry_no_local_variables(sentry_capture: CapturingTransport) -> None:
    try:
        _failing_provider_call()
    except RuntimeError as error:
        report_error(ErrorCode.LLM_EXCEPTION, error=error)
    [event] = sentry_capture.items("event")
    assert RUNTIME_SECRET not in str(event)
    frames = event["exception"]["values"][0]["stacktrace"]["frames"]
    assert all("vars" not in frame for frame in frames)


def test_a_logged_error_is_never_a_second_event(sentry_capture: CapturingTransport) -> None:
    # Sentry's loguru integration once turned each logged error into an extra, uncoded event.
    logger.error("logged outside report_error")
    report_error(ErrorCode.TTS_EXCEPTION)
    [event] = sentry_capture.items("event")
    assert event["tags"]["error_code"] == "TTS_EXCEPTION"


def test_dsn_comes_from_settings_as_a_secret() -> None:
    settings = ErrorTrackingSettings(
        dsn=SecretStr("https://public@o0.ingest.sentry.io/0"),
        environment=DeploymentEnvironment.PRODUCTION,
        release="x",
        traces_sample_rate=1,
    )
    assert "public@" not in repr(settings)
