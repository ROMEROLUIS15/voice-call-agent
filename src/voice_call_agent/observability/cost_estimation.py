"""Estimated cost of a call from its usage, duration and a versioned price table."""

import tomllib
from importlib import resources

from pydantic import BaseModel, ConfigDict

from voice_call_agent.observability.call_trace import CostEstimate, ProviderUsage, ServiceVersions

_PACKAGE = __name__.rpartition(".")[0]


class LanguageModelPrice(BaseModel):
    model_config = ConfigDict(frozen=True)

    usd_per_million_input_tokens: float
    usd_per_million_output_tokens: float


class PriceTable(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    stt_usd_per_minute: dict[str, float]
    tts_usd_per_1k_characters: dict[str, float]
    """Keyed by voice family: `aura-2` prices every `aura-2-*` voice."""
    llm: dict[str, LanguageModelPrice]
    """Keyed by `{provider}/{model}`."""
    telephony_usd_per_minute: dict[str, float]
    """Keyed by the call's channel label."""


def load_price_table() -> PriceTable:
    """Read `provider_prices.toml`. Called once at startup."""
    text = (resources.files(_PACKAGE) / "provider_prices.toml").read_text(encoding="utf-8")
    return PriceTable.model_validate(tomllib.loads(text))


def estimate_cost(
    *,
    usage: ProviderUsage,
    services: ServiceVersions,
    duration_s: float,
    channel_label: str,
    prices: PriceTable,
) -> CostEstimate:
    """Sum the priced parts; any unknown price marks the estimate as incomplete."""
    minutes = duration_s / 60
    parts: list[float | None] = [
        # Streaming STT is billed for the audio streamed, which is the whole call.
        _times(prices.stt_usd_per_minute.get(services.stt_model), minutes),
        _times(
            voice_price_per_1k_characters(prices, services.tts_voice), usage.tts_characters / 1000
        ),
        _llm_cost(prices.llm.get(f"{services.llm_provider}/{services.llm_model}"), usage),
        _times(prices.telephony_usd_per_minute.get(channel_label), minutes),
    ]
    known = [part for part in parts if part is not None]
    return CostEstimate(
        usd=round(sum(known), 6),
        complete=len(known) == len(parts),
        price_table_version=prices.version,
    )


def _times(price: float | None, quantity: float) -> float | None:
    return None if price is None else price * quantity


def voice_price_per_1k_characters(prices: PriceTable, voice: str) -> float | None:
    """The price of the voice's longest matching family, or `None` when it is not priced."""
    families = [family for family in prices.tts_usd_per_1k_characters if voice.startswith(family)]
    if not families:
        return None
    return prices.tts_usd_per_1k_characters[max(families, key=len)]


def _llm_cost(price: LanguageModelPrice | None, usage: ProviderUsage) -> float | None:
    if price is None:
        return None
    return (
        usage.llm_input_tokens * price.usd_per_million_input_tokens
        + usage.llm_output_tokens * price.usd_per_million_output_tokens
    ) / 1_000_000
