"""Load the caller-facing content of a locale.

Code is English; what the agent says to the caller lives in `<locale>/system_prompt.md`,
`<locale>/booking_prompt.md` and `<locale>/phrases.toml` next to this module (constitution:
language policy).
"""

import hashlib
import tomllib
from importlib import resources

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_LOCALE = "es"
_PACKAGE = __name__.rpartition(".")[0]


class BookingBriefing(BaseModel):
    """How the booking prompt states a business's date, opening hours and services."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    weekdays: tuple[str, ...] = Field(min_length=7, max_length=7)
    """Monday first, as `date.weekday()` counts."""
    months: tuple[str, ...] = Field(min_length=12, max_length=12)
    today: str
    open_day: str
    closed_day: str
    service: str
    price: str
    no_price: str
    """For a service whose business publishes no price."""


class ConversationContent(BaseModel):
    """Prompts and fixed phrases of one locale."""

    model_config = ConfigDict(frozen=True)

    locale: str
    system_prompt: str
    """For calls without a scheduling backend: the agent converses and books nothing."""
    booking_prompt: str
    """For calls whose business the backend resolved; filled in by `business_briefing`."""
    greeting: str
    booking_briefing: BookingBriefing

    @property
    def version(self) -> str:
        """Content hash recorded in every call trace; any edit to a prompt or phrase changes it."""
        canonical = self.model_dump_json()
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{self.locale}-{digest[:12]}"


class _Phrases(BaseModel):
    greeting: str
    booking_briefing: BookingBriefing


class UnsupportedLocaleError(Exception):
    """There is no complete content for the requested locale."""


def load_conversation_content(locale: str = DEFAULT_LOCALE) -> ConversationContent:
    """Read the locale's resources. Called once at startup, never on the event loop of a call."""
    root = resources.files(_PACKAGE) / locale
    try:
        system_prompt = (root / "system_prompt.md").read_text(encoding="utf-8").strip()
        booking_prompt = (root / "booking_prompt.md").read_text(encoding="utf-8").strip()
        phrases = _Phrases.model_validate(
            tomllib.loads((root / "phrases.toml").read_text(encoding="utf-8"))
        )
    except (FileNotFoundError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise UnsupportedLocaleError(f"Incomplete conversation content for '{locale}'") from error
    return ConversationContent(
        locale=locale,
        system_prompt=system_prompt,
        booking_prompt=booking_prompt,
        greeting=phrases.greeting,
        booking_briefing=phrases.booking_briefing,
    )
