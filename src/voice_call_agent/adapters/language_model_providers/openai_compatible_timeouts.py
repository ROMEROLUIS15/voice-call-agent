"""Explicit timeouts for OpenAI-compatible clients (Groq, OpenAI).

Pipecat builds these clients with the SDK defaults (600 s timeout, 2 retries) and exposes
`create_client` as the extension point to change them.
"""

from openai import AsyncOpenAI

_MAX_RETRIES = 1
"""At most one retry: the caller is waiting on the line."""


def with_request_timeout(client: AsyncOpenAI, timeout_seconds: float) -> AsyncOpenAI:
    """Copy of the client whose every request (connect, read, write) is bounded."""
    return client.with_options(timeout=timeout_seconds, max_retries=_MAX_RETRIES)
