"""The booking prompt of one call: the locale's template filled in with the call's business."""

from datetime import date, time

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


def booking_prompt(content: ConversationContent, business: BusinessContext, today: date) -> str:
    """The booking prompt with the business's name, today's date, its hours and its services.

    `today` is the date in the business's time zone, so "mañana" means the business's tomorrow.
    """
    briefing = content.booking_briefing
    return content.booking_prompt.format(
        business_name=business.name,
        today=_today(briefing, today),
        opening_hours="; ".join(_opening_hours(briefing, business)),
        services="\n".join(f"- {_service(briefing, service)}" for service in business.services),
    )


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
    if service.price is not None:
        line += briefing.price.format(price=service.price)
    return line


def _clock(moment: time) -> str:
    return moment.strftime("%H:%M")
