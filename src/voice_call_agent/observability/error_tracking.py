"""Error tracking (Sentry, ADR 0009): initialization and scrubbing of personal data.

Without a DSN nothing is initialized and every Sentry call in the code is a no-op.
"""

from typing import Any, cast

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration
from sentry_sdk.transport import Transport
from sentry_sdk.types import Event, Hint

from voice_call_agent.observability.personal_data_redaction import (
    PHONE_NUMBER_PATTERN,
    redact_phone_number,
)
from voice_call_agent.settings.sections import ErrorTrackingSettings

_REMOVED_KEYS = ("request", "user", "server_name")


def configure_error_tracking(
    settings: ErrorTrackingSettings, *, transport: Transport | None = None
) -> bool:
    """Initialize Sentry once at startup. Returns whether it is enabled.

    `transport` replaces Sentry's network delivery (tests capture envelopes with it).
    """
    if settings.dsn is None:
        return False
    sentry_sdk.init(
        dsn=settings.dsn.get_secret_value(),
        environment=settings.environment.value,
        release=settings.release,
        traces_sample_rate=settings.traces_sample_rate,
        send_default_pii=False,
        include_local_variables=False,  # Stack frames could hold secrets or phone numbers.
        max_request_body_size="never",
        # Errors become events only through `report_error`, with their code.
        auto_enabling_integrations=False,
        integrations=[LoggingIntegration(level=None, event_level=None)],
        # Its loguru sink would turn every logged error into a second, uncoded event.
        disabled_integrations=[LoguruIntegration()],
        before_send=scrub_event,
        before_send_transaction=scrub_event,
        transport=transport,
    )
    return True


def scrub_event(event: Event, _hint: Hint) -> Event:
    """Drop request and user data and redact phone numbers anywhere in the event."""
    for key in _REMOVED_KEYS:
        event.pop(key, None)  # type: ignore[misc]  # Event is a TypedDict; these keys are optional.
    return cast(Event, _redact(cast(Any, event)))


def _redact(value: object) -> object:
    if isinstance(value, str):
        return PHONE_NUMBER_PATTERN.sub(lambda match: redact_phone_number(match.group()), value)
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
