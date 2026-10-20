from collections.abc import Iterator

import pytest
import sentry_sdk
from pydantic import SecretStr

from tests.sentry_capture import CapturingTransport
from voice_call_agent.observability.error_tracking import configure_error_tracking
from voice_call_agent.settings.sections import DeploymentEnvironment, ErrorTrackingSettings
from voice_call_agent.settings.service_settings import ServiceSettings


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Tests never read the `.env` file or the machine's variables."""
    for name in ServiceSettings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    # Even `model_validate` reads the `.env` file of the working directory.
    monkeypatch.setitem(ServiceSettings.model_config, "env_file", None)
    yield


@pytest.fixture
def sentry_capture() -> Iterator[CapturingTransport]:
    transport = CapturingTransport()
    configure_error_tracking(
        ErrorTrackingSettings(
            dsn=SecretStr("https://public@o0.ingest.sentry.io/0"),
            environment=DeploymentEnvironment.DEVELOPMENT,
            release="voice-call-agent@test",
            traces_sample_rate=1.0,
        ),
        transport=transport,
    )
    yield transport
    sentry_sdk.flush()
    # Back to an inactive client, without setting up any integration globally.
    sentry_sdk.init(default_integrations=False, auto_enabling_integrations=False)
