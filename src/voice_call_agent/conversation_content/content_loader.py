"""Load the caller-facing content of a locale.

Code is English; what the agent says to the caller lives in `<locale>/system_prompt.md`,
`<locale>/booking_prompt.md`, `<locale>/booking_flow.toml` and `<locale>/phrases.toml` next to
this module (constitution: language policy).
"""

import hashlib
import tomllib
from importlib import resources
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
    """Takes `{price}` and `{currency}`, the currency's name from `currencies`."""
    no_price: str
    """For a service whose business publishes no price."""
    currencies: dict[str, str]
    """How each ISO 4217 code is said; a code missing here is said as the code."""
    calendar_day: str
    """A day of the calendar of the coming days, with its date for the tools."""
    calendar_today: str
    calendar_tomorrow: str
    calendar_closed: str


class SpokenMoments(BaseModel):
    """How a date and a time are said aloud, in words: the read-back, a day in a tool's result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    numbers: tuple[str, ...] = Field(min_length=60, max_length=60)
    """0 to 59, for day numbers and minutes."""
    day: str
    hours: tuple[str, ...] = Field(min_length=12, max_length=12)
    """The hour on a 12-hour clock, with its article; index 0 is twelve."""
    on_the_hour: str
    past_the_hour: str
    minute_names: dict[int, str]
    """Minutes said by name instead of by number (a quarter, a half)."""
    day_parts: tuple[tuple[int, str], ...] = Field(min_length=1)
    """The part of the day from each hour on, in order; the first starts at hour 0."""

    @model_validator(mode="after")
    def _every_hour_has_a_day_part(self) -> Self:
        starts = [start for start, _ in self.day_parts]
        if starts[0] != 0 or starts != sorted(set(starts)) or starts[-1] > 23:
            raise ValueError("day parts start at hour 0 and go up within the day")
        return self


class BookingTasks(BaseModel):
    """What the model does at each step of the booking flow (ADR 0019)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request: str
    choose_time: str
    """Takes `{service_name}`, `{day}`, `{free_times}` and `{requested}`."""
    name: str
    """Takes `{service_name}`, `{day}` and `{time}`."""
    confirm: str
    booked: str
    not_booked: str


class RequestedTimeTexts(BaseModel):
    """Why the time the caller asked for is not offered, one text per `Unavailable` reason.

    Each takes `{time}`, `{duration}`, `{opens}`, `{closes}` and `{interval}`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    outside_hours: str
    off_interval: str
    does_not_fit: str
    taken: str


class BookingChoices(BaseModel):
    """How the choose_time task says the free times: ranges of starts, or single starts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    free_time: str
    """Takes `{spoken}` and `{clock}`."""
    free_range: str
    """Takes `{first}`, `{first_clock}`, `{last}` and `{last_clock}`."""
    interval: str
    """Takes `{minutes}`."""
    requested: RequestedTimeTexts


class BookingFlowTexts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tasks: BookingTasks
    choices: BookingChoices


class ConversationContent(BaseModel):
    """Prompts and fixed phrases of one locale."""

    model_config = ConfigDict(frozen=True)

    locale: str
    system_prompt: str
    """For calls without a scheduling backend: the agent converses and books nothing."""
    booking_prompt: str
    """For calls whose business the backend resolved; filled in by `business_briefing`."""
    greeting: str
    business_greeting: str
    """Takes `{business_name}`."""
    read_back: str
    """The proposal as the code reads it back before the caller's yes (ADR 0019)."""
    booking_briefing: BookingBriefing
    spoken_moments: SpokenMoments
    booking_flow: BookingFlowTexts

    @property
    def version(self) -> str:
        """Content hash recorded in every call trace; any edit to a prompt or phrase changes it."""
        canonical = self.model_dump_json()
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{self.locale}-{digest[:12]}"


class _Phrases(BaseModel):
    greeting: str
    business_greeting: str
    """Takes `{business_name}`."""
    read_back: str
    booking_briefing: BookingBriefing
    spoken_moments: SpokenMoments


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
        booking_flow = BookingFlowTexts.model_validate(
            tomllib.loads((root / "booking_flow.toml").read_text(encoding="utf-8"))
        )
    except (FileNotFoundError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise UnsupportedLocaleError(f"Incomplete conversation content for '{locale}'") from error
    return ConversationContent(
        locale=locale,
        system_prompt=system_prompt,
        booking_prompt=booking_prompt,
        greeting=phrases.greeting,
        business_greeting=phrases.business_greeting,
        read_back=phrases.read_back,
        booking_briefing=phrases.booking_briefing,
        spoken_moments=phrases.spoken_moments,
        booking_flow=booking_flow,
    )
