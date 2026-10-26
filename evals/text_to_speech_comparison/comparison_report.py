"""Summary of the timed replies per engine and per voice, against the latency budget."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from evals.text_to_speech_comparison.synthesis_timing import SynthesisSample, VoiceRun
from voice_call_agent.observability.cost_estimation import PriceTable, voice_price_per_1k_characters
from voice_call_agent.observability.latency_budget_report import nearest_rank_percentile

_ENGINES = {"aura-2-": "Aura-2", "flux-": "Flux TTS"}
ALL_VOICES = "all voices"


@dataclass(frozen=True)
class LatencySummary:
    engine: str
    voice: str
    samples: int
    p50_ms: float
    p95_ms: float
    usd_per_1k_characters: float | None


def engine_of(voice: str) -> str:
    return next((name for prefix, name in _ENGINES.items() if voice.startswith(prefix)), "other")


def summarize(runs: Iterable[VoiceRun], prices: PriceTable) -> list[LatencySummary]:
    """One row per engine (all its voices) followed by one row per voice."""
    by_voice = {run.voice: run.samples for run in runs if run.samples}
    by_engine: dict[str, list[SynthesisSample]] = {}
    for voice, samples in by_voice.items():
        by_engine.setdefault(engine_of(voice), []).extend(samples)
    rows = [
        _summary(engine, ALL_VOICES, samples, _engine_price(samples, prices))
        for engine, samples in sorted(by_engine.items())
    ]
    rows += [
        _summary(engine_of(voice), voice, samples, voice_price_per_1k_characters(prices, voice))
        for voice, samples in sorted(
            by_voice.items(), key=lambda item: (engine_of(item[0]), item[0])
        )
    ]
    return rows


def render_report(
    summaries: Sequence[LatencySummary],
    failures: dict[str, str],
    *,
    measured_on: str,
    measured_from: str,
    tokens_per_second: float,
    price_table_version: str,
) -> str:
    lines = [
        "# Text-to-speech comparison",
        "",
        f"First language model token -> first audio (manifest §6), {measured_on}, from "
        f"{measured_from}. Replies streamed at {tokens_per_second:g} tokens per second, one word "
        "per token; audio at the phone line's 8 kHz. Prices from the price table "
        f"`{price_table_version}`.",
        "",
        "| Engine | Voice | Replies | p50 ms | p95 ms | USD per 1k characters |",
        "|---|---|---|---|---|---|",
    ]
    for row in summaries:
        price = "unknown" if row.usd_per_1k_characters is None else f"{row.usd_per_1k_characters:g}"
        lines.append(
            f"| {row.engine} | {row.voice} | {row.samples} | {row.p50_ms:.0f} | "
            f"{row.p95_ms:.0f} | {price} |"
        )
    if failures:
        lines += ["", "Voices that failed:", ""]
        lines += [f"- `{voice}`: {reason}" for voice, reason in sorted(failures.items())]
    return "\n".join(lines) + "\n"


def _summary(
    engine: str, voice: str, samples: Sequence[SynthesisSample], price: float | None
) -> LatencySummary:
    values = [sample.first_audio_ms for sample in samples]
    return LatencySummary(
        engine=engine,
        voice=voice,
        samples=len(values),
        p50_ms=nearest_rank_percentile(values, 50),
        p95_ms=nearest_rank_percentile(values, 95),
        usd_per_1k_characters=price,
    )


def _engine_price(samples: Sequence[SynthesisSample], prices: PriceTable) -> float | None:
    """The price shared by the engine's voices, or `None` when they differ or are unknown."""
    voice_prices = {voice_price_per_1k_characters(prices, sample.voice) for sample in samples}
    return voice_prices.pop() if len(voice_prices) == 1 else None
