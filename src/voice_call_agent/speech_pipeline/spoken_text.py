"""What reaches the voice: text the caller hears, with the marks that have no sound removed.

The prompt asks for plain speech; when the model still writes Markdown or invisible characters,
the voice must not read them out ("asterisco") nor stumble on them (manifest §10).
"""

import re

from pipecat.utils.text.base_text_aggregator import TextType
from pipecat.utils.text.transforms.strip_markdown import strip_markdown

from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode

_SOUNDLESS_MARKS = re.compile("[*\u200b\u200c\u200d\u2060\ufeff]")
"""Asterisks left over once Markdown is stripped, and zero-width characters."""


async def drop_soundless_marks(text: str, text_type: str | TextType) -> str:
    """Remove the marks that have no sound; the words are left as they are."""
    return _SOUNDLESS_MARKS.sub("", text)


_LEAKED_TURN = re.compile(r"(?:^|(?<=[\s.,;:!?¿¡]))(?:user|assistant)(?=[A-ZÁÉÍÓÚÑ¿¡])")
"""A chat role glued to the words that follow it ("userEl martes"): the model went on writing
the next turn of the conversation, the caller's, into its own reply."""


async def drop_leaked_turn(text: str, text_type: str | TextType) -> str:
    """Cut a turn the model wrote for someone else, from its role on: the caller never hears
    words put in their mouth."""
    leak = _LEAKED_TURN.search(text)
    if leak is None:
        return text
    report_error(ErrorCode.MODEL_LEAKED_TURN, role=leak.group())
    return text[: leak.start()]


SPOKEN_TEXT_TRANSFORMS = [
    ("*", strip_markdown),
    ("*", drop_soundless_marks),
    ("*", drop_leaked_turn),
]
"""For every text type the voice speaks, in order (Pipecat's `text_transforms`)."""
