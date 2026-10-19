import pytest

from voice_call_agent.conversation_content.content_loader import (
    UnsupportedLocaleError,
    load_conversation_content,
)


def test_spanish_content_is_complete() -> None:
    content = load_conversation_content("es")
    assert content.locale == "es"
    assert content.greeting
    assert "español" in content.system_prompt


def test_unknown_locale_is_an_error() -> None:
    with pytest.raises(UnsupportedLocaleError):
        load_conversation_content("xx")


def test_version_changes_with_the_prompt() -> None:
    content = load_conversation_content("es")
    edited = content.model_copy(update={"system_prompt": content.system_prompt + " Sé breve."})
    assert content.version.startswith("es-")
    assert edited.version != content.version
    assert load_conversation_content("es").version == content.version
