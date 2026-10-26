"""Compare text-to-speech voices: `python -m evals.text_to_speech_comparison [options]`.

Needs `DEEPGRAM_API_KEY`; only environment variables are read, never a `.env` file. Writes the
report, every timed reply (JSON lines) and phone-quality samples of each voice's replies to the
output directory. Exit code: 0 every voice spoke, 1 a voice failed, 2 the comparison could not run.
"""

import argparse
import asyncio
import json
import os
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from pipecat.services.tts_service import TTSService
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

import evals.text_to_speech_comparison as comparison_package
from evals.text_to_speech_comparison.comparison_report import render_report, summarize
from evals.text_to_speech_comparison.phone_quality_audio import phone_line_wav
from evals.text_to_speech_comparison.synthesis_timing import (
    PHONE_SAMPLE_RATE_HZ,
    REPLY_SILENCE_S,
    VoiceRun,
    create_voice_service,
    time_voice,
)
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.observability.cost_estimation import load_price_table

EXIT_OK, EXIT_VOICE_FAILED, EXIT_CANNOT_RUN = 0, 1, 2
GROQ_TOKENS_PER_SECOND = 500.0
"""Output speed Groq documents for `openai/gpt-oss-120b`, the model in use (manifest §7)."""
DEFAULT_REPETITIONS = 3
DEFAULT_VOICES = (
    # Aura-2 voices with a Latin American or Colombian accent; `selena` is the one in use.
    "aura-2-selena-es",
    "aura-2-aquila-es",
    "aura-2-celeste-es",
    "aura-2-gloria-es",
    # Every Spanish Flux TTS voice: Deepgram publishes no accent for them.
    "flux-aina-es",
    "flux-alfredo-es",
    "flux-carmen-es",
    "flux-cecilia-es",
    "flux-duvan-es",
    "flux-eduardo-es",
    "flux-ernesto-es",
    "flux-fernanda-es",
    "flux-fiorella-es",
    "flux-gustavo-es",
    "flux-jaime-es",
    "flux-martin-es",
    "flux-mauricio-es",
    "flux-patricia-es",
    "flux-pilar-es",
    "flux-rafael-es",
    "flux-tomas-es",
    "flux-valentina-es",
    "flux-ysabel-es",
)
DEFAULT_OUTPUT = Path("var/text-to-speech-comparison")


class ComparisonSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    deepgram_api_key: SecretStr | None = None


def load_replies() -> list[str]:
    """The greeting of the conversation content, then the replies of `agent_replies.toml`."""
    replies_file = resources.files(comparison_package) / "agent_replies.toml"
    text = replies_file.read_text(encoding="utf-8")
    replies: list[str] = tomllib.loads(text)["replies"]
    return [load_conversation_content().greeting, *replies]


def main(argv: list[str] | None = None) -> int:
    arguments = _arguments(argv)
    key = ComparisonSettings().deepgram_api_key
    if key is None:
        print("Cannot run: DEEPGRAM_API_KEY is needed.")
        return EXIT_CANNOT_RUN

    def create_service(voice: str) -> TTSService:
        return create_voice_service(voice, key.get_secret_value())

    return asyncio.run(
        compare(
            arguments.voices,
            load_replies(),
            create_service=create_service,
            repetitions=arguments.repetitions,
            output=arguments.output,
        )
    )


async def compare(
    voices: Sequence[str],
    replies: Sequence[str],
    *,
    create_service: Callable[[str], TTSService],
    repetitions: int,
    output: Path,
    reply_silence_s: float = REPLY_SILENCE_S,
) -> int:
    """Time each voice in turn, then write the report, the timed replies and the samples."""
    runs = [
        await time_voice(
            voice,
            replies,
            create_service=create_service,
            repetitions=repetitions,
            tokens_per_second=GROQ_TOKENS_PER_SECOND,
            reply_silence_s=reply_silence_s,
        )
        for voice in voices
    ]
    samples = {
        (run.voice, index): await phone_line_wav(pcm, PHONE_SAMPLE_RATE_HZ)
        for run in runs
        for index, pcm in run.audio_by_reply.items()
    }
    prices = load_price_table()
    failures = {run.voice: run.failure for run in runs if run.failure is not None}
    report = render_report(
        summarize(runs, prices),
        failures,
        measured_on=datetime.now(UTC).date().isoformat(),
        measured_from=(
            "a GitHub-hosted runner"
            if os.environ.get("GITHUB_ACTIONS") == "true"
            else "a local machine"
        ),
        tokens_per_second=GROQ_TOKENS_PER_SECOND,
        price_table_version=prices.version,
    )
    await asyncio.to_thread(_write_outputs, output, report, runs, samples)
    print(report)
    return EXIT_VOICE_FAILED if failures else EXIT_OK


def _write_outputs(
    output: Path, report: str, runs: Sequence[VoiceRun], samples: dict[tuple[str, int], bytes]
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.md").write_text(report, encoding="utf-8")
    with (output / "replies.jsonl").open("w", encoding="utf-8") as lines:
        for run in runs:
            lines.writelines(json.dumps(asdict(sample)) + "\n" for sample in run.samples)
    for (voice, index), wav in samples.items():
        (output / "samples" / voice).mkdir(parents=True, exist_ok=True)
        (output / "samples" / voice / f"reply-{index}.wav").write_bytes(wav)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m evals.text_to_speech_comparison")
    parser.add_argument(
        "--voices",
        type=lambda value: tuple(value.split(",")),
        default=DEFAULT_VOICES,
        help="comma-separated voices (aura-2-* or flux-*)",
    )
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
