"""OpenRouter's completions report which upstream provider served them to the call's trace."""

from collections.abc import AsyncIterator
from typing import cast

from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk

from voice_call_agent.adapters.language_model_providers.openrouter_model import (
    _UpstreamReportingStream,
)
from voice_call_agent.observability.upstream_attribution import (
    report_llm_upstream,
    upstreams_recorded_by,
)


class _Recorder:
    def __init__(self) -> None:
        self.upstreams: list[str] = []

    def record_llm_upstream(self, upstream: str) -> None:
        self.upstreams.append(upstream)


class _Stream:
    def __init__(self, chunks: list[ChatCompletionChunk]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[ChatCompletionChunk]:
        for chunk in self._chunks:
            yield chunk

    async def close(self) -> None:
        self.closed = True


def _chunk(provider: str | None) -> ChatCompletionChunk:
    data: dict[str, object] = {
        "id": "c",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "openai/gpt-oss-120b",
        "choices": [],
    }
    if provider is not None:
        data["provider"] = provider  # OpenRouter's own field, beyond OpenAI's schema.
    return ChatCompletionChunk.model_validate(data)


async def test_each_completion_reports_its_upstream_once_and_passes_every_chunk() -> None:
    recorder = _Recorder()
    source = _Stream([_chunk("Cerebras"), _chunk("Cerebras"), _chunk(None)])
    stream = _UpstreamReportingStream(cast(AsyncStream[ChatCompletionChunk], source))
    with upstreams_recorded_by(recorder):
        chunks = [chunk async for chunk in stream]
    await stream.close()
    assert len(chunks) == 3
    assert recorder.upstreams == ["Cerebras"]
    assert source.closed


def test_an_upstream_outside_a_call_is_dropped() -> None:
    report_llm_upstream("Groq")  # No call in progress: nothing to attribute it to, no error.
