from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.settings_factory import make_service_settings
from voice_call_agent.settings.sections import LanguageModelProvider, LogFormat


def test_a_local_env_file_does_not_reach_the_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("ENVIRONMENT=development\nLOG_FORMAT=text\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    settings = make_service_settings()
    assert settings.http_hardening().is_production
    assert settings.log_format is LogFormat.JSON


def test_complete_settings_enable_both_entries() -> None:
    settings = make_service_settings()
    assert settings.twilio_media_streams() is not None
    assert settings.whatsapp_calling() is not None


def test_missing_group_disables_its_entry() -> None:
    settings = make_service_settings(
        public_base_url=None, twilio_account_sid=None, twilio_auth_token=None
    )
    assert settings.twilio_media_streams() is None
    assert settings.whatsapp_calling() is not None


def test_partial_twilio_group_fails_at_startup() -> None:
    with pytest.raises(ValidationError, match="Twilio"):
        make_service_settings(twilio_auth_token=None)


def test_partial_whatsapp_group_fails_at_startup() -> None:
    with pytest.raises(ValidationError, match="WhatsApp"):
        make_service_settings(whatsapp_app_secret=None)


def test_selected_llm_provider_needs_its_key() -> None:
    with pytest.raises(ValidationError, match="openai"):
        make_service_settings(llm_provider="openai")


def test_language_model_section_carries_the_selected_key() -> None:
    section = make_service_settings(llm_provider="google", google_api_key="g-key").language_model()
    assert section.provider is LanguageModelProvider.GOOGLE
    assert section.api_key.get_secret_value() == "g-key"


def test_openrouter_is_the_default_provider_and_needs_its_own_key() -> None:
    with pytest.raises(ValidationError, match="openrouter"):
        make_service_settings(openrouter_api_key=None, groq_api_key="groq-key")
    section = make_service_settings().language_model()
    assert section.provider is LanguageModelProvider.OPENROUTER
    assert section.api_key.get_secret_value() == "or-key"


def test_groq_directly_needs_its_own_key() -> None:
    with pytest.raises(ValidationError, match="groq"):
        make_service_settings(llm_provider="groq")
    section = make_service_settings(llm_provider="groq", groq_api_key="groq-key").language_model()
    assert section.provider is LanguageModelProvider.GROQ


def test_validation_errors_do_not_echo_the_input() -> None:
    with pytest.raises(ValidationError) as error:
        make_service_settings(port="token-pasted-in-the-wrong-variable")
    assert "token-pasted-in-the-wrong-variable" not in str(error.value)


def test_secrets_are_masked_in_repr() -> None:
    assert "twilio-auth-token" not in repr(make_service_settings())


def test_supervision_and_logging_defaults() -> None:
    settings = make_service_settings()
    assert settings.call_supervision().max_concurrent_calls >= 1
    assert settings.logging_output().output_format is LogFormat.JSON


def test_concurrency_limit_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        make_service_settings(max_concurrent_calls=0).call_supervision()


def test_speech_ends_a_paused_turn_after_two_and_a_half_seconds_unless_configured() -> None:
    # Flux's own default, 5 s, left a caller who paused mid-sentence waiting over 6 s.
    assert make_service_settings().speech().eot_timeout_ms == 2500
    assert make_service_settings(stt_eot_timeout_ms=1800).speech().eot_timeout_ms == 1800
    with pytest.raises(ValidationError):
        make_service_settings(stt_eot_timeout_ms=100)
