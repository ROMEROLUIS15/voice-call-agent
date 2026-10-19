"""Time to the first spoken token of each language model provider (one-off measurement).

Same system prompt and the same caller turns (fictitious data) for every configuration,
interleaved so that network changes affect all of them alike. Each answer is streamed; the
time to the first content token is what the voice waits for. Runs on a GitHub-hosted runner
from a pull request that is never merged.
"""

import asyncio
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from openai import AsyncOpenAI, RateLimitError

SYSTEM_PROMPT = Path("src/voice_call_agent/conversation_content/es/system_prompt.md").read_text(
    encoding="utf-8"
)
CALLER_TURNS = (
    "Hola, buenas tardes, quisiera agendar un corte de cabello para mañana en la tarde.",
    "¿Cuánto cuesta un manicure y cuánto dura?",
    "Me llamo Carla Pérez y mi número es cero cuatro catorce, cinco cinco cinco, uno dos tres.",
    "¿Ustedes abren los sábados? ¿Hasta qué hora?",
    "No, mejor otro día. ¿El jueves a las tres puede ser?",
)
# Keeps Groq's free tier (a few thousand tokens per minute) from rejecting requests.
PAUSE_SECONDS = 3.0


@dataclass(frozen=True)
class Configuration:
    label: str
    base_url: str
    key_variable: str
    model: str
    extra_body: dict[str, object]


CONFIGURATIONS = (
    Configuration(
        "Groq gpt-oss-120b (current settings)",
        "https://api.groq.com/openai/v1",
        "GROQ_API_KEY",
        "openai/gpt-oss-120b",
        {},
    ),
    Configuration(
        "Groq gpt-oss-120b (reasoning low)",
        "https://api.groq.com/openai/v1",
        "GROQ_API_KEY",
        "openai/gpt-oss-120b",
        {"reasoning_effort": "low"},
    ),
    Configuration(
        "DeepSeek deepseek-flash (thinking off, Pipecat's default)",
        "https://api.deepseek.com/v1",
        "DEEPSEEK_API_KEY",
        "deepseek-flash",
        {"thinking": {"type": "disabled"}},
    ),
)


@dataclass
class Outcomes:
    first_token_ms: list[int] = field(default_factory=list)
    total_ms: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    samples: dict[str, str] = field(default_factory=dict)


async def answer(
    client: AsyncOpenAI, configuration: Configuration, turn: str
) -> tuple[int, int, str]:
    started = time.perf_counter()
    first: float | None = None
    pieces: list[str] = []
    stream = await client.chat.completions.create(
        model=configuration.model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": turn},
        ],
        stream=True,
        extra_body=configuration.extra_body or None,
    )
    async for chunk in stream:
        for choice in chunk.choices:
            if choice.delta.content:
                if first is None:
                    first = time.perf_counter() - started
                pieces.append(choice.delta.content)
    if first is None:
        raise RuntimeError("no content tokens")
    return round(first * 1000), round((time.perf_counter() - started) * 1000), "".join(pieces)


def nearest_rank(values: list[int], share: float) -> int:
    ordered = sorted(values)
    return ordered[max(1, math.ceil(share * len(ordered))) - 1]


async def measure(rounds: int) -> dict[str, Outcomes]:
    clients = {
        c.label: AsyncOpenAI(
            base_url=c.base_url, api_key=os.environ[c.key_variable], timeout=30, max_retries=0
        )
        for c in CONFIGURATIONS
    }
    for c in CONFIGURATIONS:  # Warm-up, not counted: a call reuses its open connection.
        try:
            await answer(clients[c.label], c, CALLER_TURNS[0])
        except Exception as error:  # Reported with the results below.
            print(f"warm-up {c.label}: {type(error).__name__}")
        await asyncio.sleep(PAUSE_SECONDS)
    results = {c.label: Outcomes() for c in CONFIGURATIONS}
    for _ in range(rounds):
        for turn in CALLER_TURNS:
            for c in CONFIGURATIONS:
                outcomes = results[c.label]
                try:
                    first, total, text = await answer(clients[c.label], c, turn)
                except RateLimitError:
                    outcomes.errors.append("rate limited")
                except Exception as error:  # Counted, never hidden.
                    outcomes.errors.append(type(error).__name__)
                else:
                    outcomes.first_token_ms.append(first)
                    outcomes.total_ms.append(total)
                    outcomes.samples.setdefault(turn, text)
                await asyncio.sleep(PAUSE_SECONDS)
    return results


def report(results: dict[str, Outcomes]) -> str:
    lines = [
        "| Configuration | First token p50 | First token p95 | Full answer p50 | OK | Errors |",
        "|---|---|---|---|---|---|",
    ]
    for label, o in results.items():
        if o.first_token_ms:
            lines.append(
                f"| {label} | {statistics.median(o.first_token_ms):.0f} ms"
                f" | {nearest_rank(o.first_token_ms, 0.95)} ms"
                f" | {statistics.median(o.total_ms):.0f} ms | {len(o.first_token_ms)}"
                f" | {len(o.errors)} {sorted(set(o.errors))} |"
            )
        else:
            lines.append(f"| {label} | - | - | - | 0 | {len(o.errors)} {sorted(set(o.errors))} |")
    for label, o in results.items():
        lines += ["", f"### {label}", ""]
        lines += [f"*   **{turn}** → {text}" for turn, text in o.samples.items()]
    return "\n".join(lines)


def main() -> None:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    text = report(asyncio.run(measure(rounds)))
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write(text + "\n")


if __name__ == "__main__":
    main()
