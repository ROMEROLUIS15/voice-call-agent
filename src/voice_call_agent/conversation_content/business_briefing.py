"""The booking prompt of one call: the locale's template filled in with the call's business."""

from datetime import date, time, timedelta

from voice_call_agent.conversation_content.content_loader import (
    BookingBriefing,
    ConversationContent,
)
from voice_call_agent.scheduling_backend.scheduling_models import (
    BusinessContext,
    OpeningHours,
    ServiceOffering,
)

_WEEKDAY_FIELDS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CALENDAR_DAYS = 14
"""Today and the next thirteen days: two weeks cover a weekday of next week on any day."""


def booking_prompt(content: ConversationContent, business: BusinessContext, today: date) -> str:
    """The booking prompt with the business's name, today's date, its hours and its services.

    `today` is the date in the business's time zone, so "mañana" means the business's tomorrow.
    """
    briefing = content.booking_briefing
    return content.booking_prompt.format(
        business_name=business.name,
        today=_today(briefing, today),
        opening_hours="; ".join(_opening_hours(briefing, business)),
        calendar="\n".join(f"- {line}" for line in _calendar(briefing, business, today)),
        services="\n".join(f"- {_service(briefing, service)}" for service in business.services),
    )


def _calendar(briefing: BookingBriefing, business: BusinessContext, today: date) -> list[str]:
    """Each coming day with its weekday and its date: the model looks a day up instead of
    computing it, which it gets wrong (manifest §10)."""
    notes = {0: briefing.calendar_today, 1: briefing.calendar_tomorrow}
    lines = []
    for offset in range(CALENDAR_DAYS):
        day = today + timedelta(days=offset)
        closed = getattr(business.weekly_hours, _WEEKDAY_FIELDS[day.weekday()]) is None
        lines.append(
            briefing.calendar_day.format(
                weekday=briefing.weekdays[day.weekday()],
                day=day.day,
                month=briefing.months[day.month - 1],
                note=notes.get(offset, ""),
                iso_date=day.isoformat(),
                closed=briefing.calendar_closed if closed else "",
            )
        )
    return lines


def _today(briefing: BookingBriefing, today: date) -> str:
    return briefing.today.format(
        weekday=briefing.weekdays[today.weekday()],
        day=today.day,
        month=briefing.months[today.month - 1],
        year=today.year,
        iso_date=today.isoformat(),
    )


def _opening_hours(briefing: BookingBriefing, business: BusinessContext) -> list[str]:
    lines = []
    for weekday, field in zip(briefing.weekdays, _WEEKDAY_FIELDS, strict=True):
        hours: OpeningHours | None = getattr(business.weekly_hours, field)
        if hours is None:
            lines.append(briefing.closed_day.format(weekday=weekday))
        else:
            lines.append(
                briefing.open_day.format(
                    weekday=weekday, opens=_clock(hours.opens), closes=_clock(hours.closes)
                )
            )
    return lines


def _service(briefing: BookingBriefing, service: ServiceOffering) -> str:
    line = briefing.service.format(name=service.name, id=service.id, minutes=service.duration_min)
    # Said, not left out: a service listed without a price reads as a free one (manifest §10).
    if service.price is None:
        line += briefing.no_price
    else:
        line += briefing.price.format(price=service.price)
    return line


def _clock(moment: time) -> str:
    return moment.strftime("%H:%M")
