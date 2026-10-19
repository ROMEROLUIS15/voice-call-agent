"""`.env.example` documents exactly the variables the service reads."""

import re
from pathlib import Path

from voice_call_agent.settings.service_settings import ServiceSettings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def _documented_variables() -> set[str]:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    return {match.group(1) for line in lines if (match := re.match(r"^([A-Z0-9_]+)=", line))}


def test_every_setting_is_documented() -> None:
    expected = {name.upper() for name in ServiceSettings.model_fields}
    assert expected - _documented_variables() == set()


def test_no_stale_variable_is_documented() -> None:
    expected = {name.upper() for name in ServiceSettings.model_fields}
    assert _documented_variables() - expected == set()


def test_example_holds_no_secret_values() -> None:
    secrets = {
        name.upper()
        for name in ServiceSettings.model_fields
        if "token" in name or "key" in name or "secret" in name
    }
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name in secrets:
            assert value == "", f"{name} must be empty in .env.example"
