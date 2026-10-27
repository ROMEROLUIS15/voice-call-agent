"""The service's model through OpenRouter, served by Groq or, when Groq fails, by Cerebras.

OpenRouter routes each request to Groq first and, on a rate limit or failure, to Cerebras: the
same model on both, with every parameter the service sends, and only through providers that do
not collect the data (manifest §10, §11). Which one answered goes to the call trace.
"""

from collections.abc import AsyncIterator, Callable, Mapping

from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletionChunk
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.ai_service import AIService
from pipecat.services.openrouter.llm import (
    OpenRouterLLMService,
    OpenRouterLLMSettings,
    OpenRouterProviderPreferences,
)

from voice_call_agent.adapters.language_model_providers.openai_compatible_timeouts import (
    with_request_timeout,
)
from voice_call_agent.observability.upstream_attribution import report_llm_upstream
from voice_call_agent.settings.sections import LanguageModelSettings

DEFAULT_MODEL = "openai/gpt-oss-120b"
"""OpenRouter's id for the model the service uses (manifest §7)."""
GROQ_THEN_CEREBRAS = OpenRouterProviderPreferences(
    order=["groq", "cerebras"],
    only=["groq", "cerebras"],
    allow_fallbacks=False,
    require_parameters=True,
    data_collection="deny",
)
"""Groq first, Cerebras when Groq fails, never another provider: both serve the same model with
tools and reasoning effort, and neither may collect the call's data."""


class TimeBoundOpenRouterLLMService(OpenRouterLLMService):
    """`OpenRouterLLMService` whose HTTP client has an explicit request timeout."""

    def __init__(
        self, *, api_key: str, settings: OpenRouterLLMSettings, request_timeout_seconds: float
    ) -> None:
        # The base initializer calls `create_client`, so the timeout is stored first.
        self._request_timeout_seconds = request_timeout_seconds
        super().__init__(api_key=api_key, settings=settings)

    def create_client(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        default_headers: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> AsyncOpenAI:
        # Pipecat's `create_client` carries no annotations.
        client = super().create_client(  # type: ignore[no-untyped-call]
            api_key=api_key,
            base_url=base_url,
            organization=organization,
            project=project,
            default_headers=default_headers,
            **kwargs,
        )
        return with_request_timeout(client, self._request_timeout_seconds)

    async def get_chat_completions(self, context: LLMContext) -> AsyncStream[ChatCompletionChunk]:
        stream = await super().get_chat_completions(context)
        # The wrapper keeps the stream's interface (iteration and closing), not its type.
        return _UpstreamReportingStream(stream)  # type: ignore[return-value]


class _UpstreamReportingStream:
    """A completion stream that reports which upstream provider OpenRouter routed it to."""

    def __init__(self, stream: AsyncStream[ChatCompletionChunk]) -> None:
        self._stream = stream

    def __aiter__(self) -> AsyncIterator[ChatCompletionChunk]:
        return self._chunks()

    async def _chunks(self) -> AsyncIterator[ChatCompletionChunk]:
        reported = False
        async for chunk in self._stream:
            upstream = (chunk.model_extra or {}).get("provider")
            if not reported and isinstance(upstream, str):
                report_llm_upstream(upstream)
                reported = True
            yield chunk

    async def close(self) -> None:
        await self._stream.close()


def openrouter_model_factory(settings: LanguageModelSettings) -> Callable[[str], AIService]:
    api_key = settings.api_key.get_secret_value()

    def create(system_prompt: str) -> AIService:
        model_settings = OpenRouterLLMSettings(
            system_instruction=system_prompt,
            model=settings.model or DEFAULT_MODEL,
            provider=GROQ_THEN_CEREBRAS,
        )
        if not settings.model:
            # The same low reasoning effort as on Groq directly (manifest §7), in OpenRouter's
            # own request field.
            model_settings.extra = {"extra_body": {"reasoning": {"effort": "low"}}}
        return TimeBoundOpenRouterLLMService(
            api_key=api_key,
            settings=model_settings,
            request_timeout_seconds=settings.request_timeout_seconds,
        )

    return create
