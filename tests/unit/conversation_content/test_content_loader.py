import pytest

from tests.practice_catalogs import MONDAY, TWO_BUSINESSES
from voice_call_agent.conversation_content.business_briefing import booking_prompt
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


def test_the_booking_prompt_states_the_business_and_omits_missing_prices() -> None:
    business = TWO_BUSINESSES.business("barbershop").context(None)
    prompt = booking_prompt(load_conversation_content(), business, MONDAY)
    assert "Barbería Uno" in prompt and "2026-10-26" in prompt
    assert "Corte y barba [full]: 60 minutos, precio no publicado" in prompt  # Said, not omitted.
    assert "Corte [haircut]: 30 minutos, precio 8.00" in prompt
    assert "sábado cerrado" in prompt
