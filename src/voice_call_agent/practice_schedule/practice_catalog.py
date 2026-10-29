"""The fictitious businesses of the practice schedule, read once at startup."""

import tomllib
from importlib import resources
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from voice_call_agent.scheduling_backend.scheduling_models import (
    BusinessContext,
    OpeningHours,
    ServiceOffering,
    WeeklyHours,
)

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
"""In `date.weekday()` order."""


class PracticeBusiness(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    timezone: str
    greeting: str
    """Distance between the start times offered."""
    dialed_numbers: tuple[str, ...] = ()
    services: tuple[ServiceOffering, ...] = Field(min_length=1)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    opening_hours: dict[Weekday, OpeningHours]
    """A day that is not listed is closed."""

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def weekly_hours(self) -> WeeklyHours:
        return WeeklyHours(**{day: self.opening_hours.get(day) for day in WEEKDAYS})

    def service(self, service_id: str) -> ServiceOffering | None:
        return next((service for service in self.services if service.id == service_id), None)

    def context(self, known_client_first_name: str | None) -> BusinessContext:
        return BusinessContext(
            name=self.name,
            timezone=self.timezone,
            greeting=self.greeting,
            recording_enabled=False,
            services=list(self.services),
            weekly_hours=self.weekly_hours,
            currency=self.currency,
            known_client_first_name=known_client_first_name,
        )

    @field_validator("services", mode="before")
    @classmethod
    def _unpriced_services(cls, services: object) -> object:
        """A service listed without a price has none: TOML cannot write a missing value."""
        if not isinstance(services, list):
            return services
        return [{"price": None} | s if isinstance(s, dict) else s for s in services]

    @model_validator(mode="after")
    def _check(self) -> Self:
        try:
            ZoneInfo(self.timezone)  # An unknown time zone fails at startup, not on a call.
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"business {self.id}: unknown time zone {self.timezone}") from error
        if any(hours.closes <= hours.opens for hours in self.opening_hours.values()):
            raise ValueError(f"business {self.id}: a day closes before it opens")
        if len({service.id for service in self.services}) != len(self.services):
            raise ValueError(f"business {self.id}: repeated service id")
        return self


class PracticeCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    default_business: str
    """Reached by every call whose dialed number no business lists."""
    businesses: tuple[PracticeBusiness, ...] = Field(min_length=1)

    def business(self, business_id: str) -> PracticeBusiness:
        return next(business for business in self.businesses if business.id == business_id)

    def business_for_number(self, dialed_phone: str | None) -> PracticeBusiness:
        """The business that lists the dialed number, or the default one."""
        for business in self.businesses:
            if dialed_phone is not None and dialed_phone in business.dialed_numbers:
                return business
        return self.business(self.default_business)

    @model_validator(mode="after")
    def _check(self) -> Self:
        ids = [business.id for business in self.businesses]
        if len(set(ids)) != len(ids):
            raise ValueError("repeated business id")
        if self.default_business not in ids:
            raise ValueError("the default business is not in the catalog")
        numbers = [number for business in self.businesses for number in business.dialed_numbers]
        if len(set(numbers)) != len(numbers):
            raise ValueError("a dialed number reaches two businesses")
        return self


def load_practice_catalog() -> PracticeCatalog:
    """Read `practice_businesses.toml`. Called once at startup."""
    text = (resources.files(__package__) / "practice_businesses.toml").read_text(encoding="utf-8")
    return PracticeCatalog.model_validate(tomllib.loads(text))
