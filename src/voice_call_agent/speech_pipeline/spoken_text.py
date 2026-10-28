"""What reaches the voice: text the caller hears, with the marks that have no sound removed.

The prompt asks for plain speech; when the model still writes Markdown or invisible characters,
the voice must not read them out ("asterisco") nor stumble on them (manifest §10).
"""

import re

from pipecat.utils.text.base_text_aggregator import TextType
from pipecat.utils.text.transforms.strip_markdown import strip_markdown

_SOUNDLESS_MARKS = re.compile("[*\u200b\u200c\u200d\u2060\ufeff]")
"""Asterisks left over once Markdown is stripped, and zero-width characters."""


async def drop_soundless_marks(text: str, text_type: str | TextType) -> str:
    """Remove the marks that have no sound; the words are left as they are."""
    return _SOUNDLESS_MARKS.sub("", text)


SPOKEN_TEXT_TRANSFORMS = [("*", strip_markdown), ("*", drop_soundless_marks)]
"""For every text type the voice speaks, in order (Pipecat's `text_transforms`)."""
