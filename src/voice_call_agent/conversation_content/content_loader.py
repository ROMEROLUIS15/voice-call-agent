"""Load the caller-facing content of a locale.

Code is English; what the agent says to the caller lives in `<locale>/system_prompt.md` and
`<locale>/phrases.toml` next to this module (constitution: language policy).
"""

import hashlib
import json
import tomllib
from importlib import resources

from pydantic import BaseModel, ConfigDict, ValidationError

DEFAULT_LOCALE = "es"
_PACKAGE = __name__.rpartition(".")[0]


class ConversationContent(BaseModel):
    """Prompt and fixed phrases of one locale."""

    model_config = ConfigDict(frozen=True)

    locale: str
    system_prompt: str
    greeting: str

    @property
    def version(self) -> str:
        """Content hash recorded in every call trace; any edit to a prompt or phrase changes it."""
        canonical = json.dumps([self.locale, self.system_prompt, self.greeting])
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{self.locale}-{digest[:12]}"


class _Phrases(BaseModel):
    greeting: str


class UnsupportedLocaleError(Exception):
    """There is no complete content for the requested locale."""


def load_conversation_content(locale: str = DEFAULT_LOCALE) -> ConversationContent:
    """Read the locale's resources. Called once at startup, never on the event loop of a call."""
    root = resources.files(_PACKAGE) / locale
    try:
        system_prompt = (root / "system_prompt.md").read_text(encoding="utf-8").strip()
        phrases = _Phrases.model_validate(
            tomllib.loads((root / "phrases.toml").read_text(encoding="utf-8"))
        )
    except (FileNotFoundError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise UnsupportedLocaleError(f"Incomplete conversation content for '{locale}'") from error
    return ConversationContent(
        locale=locale, system_prompt=system_prompt, greeting=phrases.greeting
    )
