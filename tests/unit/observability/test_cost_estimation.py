import pytest

from tests.call_trace_factory import SERVICES
from voice_call_agent.observability.call_trace import ProviderUsage
from voice_call_agent.observability.cost_estimation import (
    estimate_cost,
    load_price_table,
    voice_price_per_1k_characters,
)

PRICES = load_price_table()
USAGE = ProviderUsage(llm_input_tokens=10_000, llm_output_tokens=2_000, tts_characters=1_000)


def test_phone_line_call_with_known_prices_is_complete() -> None:
    cost = estimate_cost(
        usage=USAGE, services=SERVICES, duration_s=120, channel_label="twilio", prices=PRICES
    )
    stt = 2 * 0.0078
    tts = 1.0 * 0.030
    llm = (10_000 * 0.15 + 2_000 * 0.60) / 1_000_000
    telephony = 2 * 0.0129
    assert cost.usd == pytest.approx(stt + tts + llm + telephony)
    assert cost.complete
    assert cost.price_table_version == PRICES.version


def test_unknown_price_makes_the_estimate_incomplete_not_invented() -> None:
    cost = estimate_cost(
        usage=USAGE, services=SERVICES, duration_s=120, channel_label="whatsapp", prices=PRICES
    )
    assert not cost.complete
    assert cost.usd == pytest.approx(2 * 0.0078 + 0.030 + 0.0027)


def test_unknown_model_is_left_out() -> None:
    services = SERVICES.model_copy(update={"llm_model": "unpriced-model"})
    cost = estimate_cost(
        usage=USAGE, services=services, duration_s=60, channel_label="twilio", prices=PRICES
    )
    assert not cost.complete


@pytest.mark.parametrize(
    ("voice", "price"),
    [("aura-2-selena-es", 0.030), ("flux-carmen-es", 0.045), ("unpriced-voice", None)],
)
def test_voice_price_comes_from_its_family(voice: str, price: float | None) -> None:
    assert voice_price_per_1k_characters(PRICES, voice) == price


def test_browser_practice_call_through_openrouter_is_complete() -> None:
    services = SERVICES.model_copy(update={"llm_provider": "openrouter"})
    cost = estimate_cost(
        usage=USAGE, services=services, duration_s=120, channel_label="browser", prices=PRICES
    )
    assert cost.complete
    assert cost.usd == pytest.approx(2 * 0.0078 + 0.030 + 0.0027)  # No carrier minutes.
