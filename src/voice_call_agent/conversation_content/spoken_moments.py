"""Dates, times and the proposal read-back as the agent says them, in the locale's words.

The code states these facts instead of the model working them out: a model that computes a
weekday or reads back a summary gets them wrong (manifest §10, ADR 0019).
"""

from collections.abc import Sequence
from datetime import date, time

from voice_call_agent.conversation_content.content_loader import ConversationContent


def spoken_day(content: ConversationContent, day: date) -> str:
    """'martes tres de noviembre': the weekday, the day in words and the month."""
    words, briefing = content.spoken_moments, content.booking_briefing
    return words.day.format(
        weekday=briefing.weekdays[day.weekday()],
        day=words.numbers[day.day],
        month=briefing.months[day.month - 1],
    )


def spoken_time(content: ConversationContent, moment: time) -> str:
    """'las tres y media de la tarde': the hour with its article, the minutes and the day part."""
    words = content.spoken_moments
    hour = words.hours[moment.hour % 12]
    day_part = next(part for start, part in reversed(words.day_parts) if moment.hour >= start)
    if moment.minute == 0:
        return words.on_the_hour.format(hour=hour, day_part=day_part)
    minutes = words.minute_names.get(moment.minute, words.numbers[moment.minute])
    return words.past_the_hour.format(hour=hour, minutes=minutes, day_part=day_part)


def which_day_question(content: ConversationContent, said_date: date, weekday_date: date) -> str:
    """'El cuatro de noviembre es miércoles. ¿La cita es para el miércoles cuatro de noviembre o
    para el jueves cinco de noviembre?': the weekdays are the calendar's, never the model's."""
    words, briefing = content.spoken_moments, content.booking_briefing
    return content.which_day.format(
        date=f"{words.numbers[said_date.day]} de {briefing.months[said_date.month - 1]}",
        weekday=briefing.weekdays[said_date.weekday()],
        said_day=spoken_day(content, said_date),
        weekday_day=spoken_day(content, weekday_date),
    )


def proposal_read_back(
    content: ConversationContent,
    service: str,
    day: date,
    start: time,
    client_name: str,
    waiting: Sequence[str] = (),
) -> str:
    """The proposal as the caller hears it before saying yes, built from what will be written,
    and the services that wait for it ('Después seguimos con corte y barba')."""
    said = {
        "service": service,
        "day": spoken_day(content, day),
        "time": spoken_time(content, start),
        "name": client_name,
    }
    if not waiting:
        return content.read_back.format(**said)
    names = [_in_a_sentence(name) for name in waiting]
    joiner = content.booking_flow.choices.said.last_joiner
    listed = joiner.join([", ".join(names[:-1]), names[-1]]) if len(names) > 1 else names[0]
    return content.read_back_then.format(**said, next=listed)


def day_closed(content: ConversationContent, day: date) -> str:
    """'El domingo uno de noviembre no se atiende…': the day as the calendar says it."""
    return content.closed_day.format(day=spoken_day(content, day))


def day_full(content: ConversationContent, day: date) -> str:
    """'El martes veintisiete de octubre ya no quedan horas libres…'."""
    return content.no_free_starts.format(day=spoken_day(content, day))


def booked_then(
    content: ConversationContent, service: str, day: date, start: time, following: str
) -> str:
    """'Listo, la cita de corte de cabello quedó agendada para el martes…, a las once de la
    mañana. Ahora, la de corte y barba.': the booking done, then the next service asked for."""
    return content.booked_next.format(
        service=_in_a_sentence(service),
        day=spoken_day(content, day),
        time=spoken_time(content, start),
        next=_in_a_sentence(following),
    )


def _in_a_sentence(name: str) -> str:
    """A catalog name inside a sentence: 'Corte de cabello' → 'corte de cabello'; a name whose
    second letter is a capital (an acronym) is kept."""
    return name[:1].lower() + name[1:] if name[1:2].islower() else name


def booking_done(content: ConversationContent, day: date, start: time) -> str:
    """What the caller hears once the backend confirmed the booking, built from what was booked."""
    return content.booked.format(day=spoken_day(content, day), time=spoken_time(content, start))
