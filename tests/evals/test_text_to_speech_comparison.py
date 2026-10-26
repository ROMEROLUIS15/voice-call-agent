"""The text-to-speech comparison, with the scripted TTS service instead of Deepgram."""

import io
import json
import wave
from pathlib import Path

import pytest
from pipecat.services.deepgram.flux.tts import DeepgramFluxTTSService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.tts_service import TTSService

from evals.conversation_harness.scripted_speech import RecordingTextToSpeech
from evals.text_to_speech_comparison.__main__ import (
    EXIT_CANNOT_RUN,
    EXIT_OK,
    EXIT_VOICE_FAILED,
    compare,
    load_replies,
    main,
)
from evals.text_to_speech_comparison.comparison_report import (
    ALL_VOICES,
    engine_of,
    render_report,
    summarize,
)
from evals.text_to_speech_comparison.phone_quality_audio import phone_line_wav
from evals.text_to_speech_comparison.synthesis_timing import (
    PHONE_SAMPLE_RATE_HZ,
    SynthesisSample,
    VoiceRun,
    create_voice_service,
    reply_tokens,
    time_voice,
)
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.observability.cost_estimation import load_price_table

PRICES = load_price_table()


def _scripted_service(_voice: str) -> TTSService:
    return RecordingTextToSpeech()


def test_reply_tokens_are_words_that_rebuild_the_reply() -> None:
    text = "Claro. ¿A qué hora prefieres?"
    assert reply_tokens(text) == ["Claro. ", "¿A ", "qué ", "hora ", "prefieres?"]
    assert "".join(reply_tokens(text)) == text


def test_each_voice_family_gets_its_own_service() -> None:
    assert isinstance(create_voice_service("aura-2-selena-es", "key"), DeepgramTTSService)
    assert isinstance(create_voice_service("flux-carmen-es", "key"), DeepgramFluxTTSService)
    with pytest.raises(ValueError, match="unknown voice family"):
        create_voice_service("other-voice", "key")


def test_replies_start_with_the_greeting_of_the_conversation_content() -> None:
    replies = load_replies()
    assert replies[0] == load_conversation_content().greeting
    assert len(replies) > 1


def test_summary_has_a_row_per_engine_then_per_voice_with_its_price() -> None:
    runs = [
        _run("aura-2-selena-es", [300.0, 500.0]),
        _run("flux-carmen-es", [100.0, 200.0]),
        _run("flux-tomas-es", [150.0]),
    ]
    rows = summarize(runs, PRICES)
    assert [(row.engine, row.voice) for row in rows] == [
        ("Aura-2", ALL_VOICES),
        ("Flux TTS", ALL_VOICES),
        ("Aura-2", "aura-2-selena-es"),
        ("Flux TTS", "flux-carmen-es"),
        ("Flux TTS", "flux-tomas-es"),
    ]
    flux = rows[1]
    assert (flux.samples, flux.p50_ms, flux.p95_ms) == (3, 150.0, 200.0)
    assert flux.usd_per_1k_characters == pytest.approx(0.045)
    assert rows[0].usd_per_1k_characters == pytest.approx(0.030)


def test_unknown_voice_is_reported_without_a_price() -> None:
    rows = summarize([_run("other-voice", [100.0])], PRICES)
    assert engine_of("other-voice") == "other"
    assert rows[0].usd_per_1k_characters is None
    assert "| unknown |" in render_report(
        rows,
        {},
        measured_on="2026-10-26",
        measured_from="a local machine",
        tokens_per_second=500,
        price_table_version=PRICES.version,
    )


def test_report_lists_the_voices_that_failed() -> None:
    report = render_report(
        summarize([_run("flux-carmen-es", [120.0])], PRICES),
        {"flux-pilar-es": "no audio for a reply"},
        measured_on="2026-10-26",
        measured_from="a GitHub-hosted runner",
        tokens_per_second=500,
        price_table_version=PRICES.version,
    )
    assert "| Flux TTS | flux-carmen-es | 1 | 120 | 120 | 0.045 |" in report
    assert "- `flux-pilar-es`: no audio for a reply" in report


async def test_phone_line_wav_keeps_the_length_at_8_khz() -> None:
    pcm = bytes(range(256)) * 32
    with wave.open(io.BytesIO(await phone_line_wav(pcm, PHONE_SAMPLE_RATE_HZ))) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (8000, 1, 2)
        assert wav.getnframes() == len(pcm) // 2


async def test_a_voice_is_timed_on_every_reply_and_keeps_its_first_audio() -> None:
    run = await time_voice(
        "scripted",
        ["Hola, gracias por llamar.", "Claro, ¿a qué hora?"],
        create_service=_scripted_service,
        repetitions=2,
        tokens_per_second=500,
        reply_silence_s=0.05,
    )
    assert run.failure is None
    assert [(s.reply_index, s.repetition) for s in run.samples] == [(0, 0), (1, 0), (0, 1), (1, 1)]
    assert all(sample.first_audio_ms >= 0 for sample in run.samples)
    assert set(run.audio_by_reply) == {0, 1}
    assert all(run.audio_by_reply.values())


async def test_a_voice_that_never_starts_fails_without_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("evals.text_to_speech_comparison.synthesis_timing._START_TIMEOUT_S", 0.0)
    run = await time_voice(
        "scripted",
        ["Hola."],
        create_service=_scripted_service,
        repetitions=1,
        tokens_per_second=500,
    )
    assert run.failure == "the service did not start"
    assert run.samples == []


async def test_comparison_writes_the_report_the_replies_and_the_samples(tmp_path: Path) -> None:
    exit_code = await compare(
        ["scripted-a", "scripted-b"],
        ["Hola, gracias por llamar."],
        create_service=_scripted_service,
        repetitions=1,
        output=tmp_path,
        reply_silence_s=0.05,
    )
    assert exit_code == EXIT_OK
    assert "# Text-to-speech comparison" in (tmp_path / "report.md").read_text(encoding="utf-8")
    replies = (tmp_path / "replies.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["voice"] for line in replies] == ["scripted-a", "scripted-b"]
    assert (tmp_path / "samples" / "scripted-a" / "reply-0.wav").stat().st_size > 44


async def test_comparison_fails_when_a_voice_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("evals.text_to_speech_comparison.synthesis_timing._START_TIMEOUT_S", 0.0)
    exit_code = await compare(
        ["scripted"], ["Hola."], create_service=_scripted_service, repetitions=1, output=tmp_path
    )
    assert exit_code == EXIT_VOICE_FAILED
    assert "the service did not start" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_comparison_needs_the_deepgram_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    assert main([]) == EXIT_CANNOT_RUN


def _run(voice: str, first_audio_ms: list[float]) -> VoiceRun:
    samples = [SynthesisSample(voice, 0, index, ms, 100) for index, ms in enumerate(first_audio_ms)]
    return VoiceRun(voice, samples=samples)
