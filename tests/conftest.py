from collections.abc import Iterator

import pytest

from voice_call_agent.settings.service_settings import ServiceSettings


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Tests never read the `.env` file or the machine's variables."""
    for name in ServiceSettings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    yield
