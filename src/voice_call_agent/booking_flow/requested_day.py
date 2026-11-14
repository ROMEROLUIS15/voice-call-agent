"""The day a caller asked for, worked out by the code from their words, never the model's date
(ADR 0019): a weekday, a day number and a month, or today, tomorrow and the day after, as long
as the caller said them."""

from datetime import date

from voice_call_agent.booking_flow.flow_arguments import CheckAvailabilityArguments
from voice_call_agent.booking_flow.named_day import (
    DayQuestion,
    NamedDay,
    UnknownNamedDayError,
    day_question,
    day_said,
)
from voice_call_agent.booking_flow.said_day import said_day
from voice_call_agent.booking_flow.step_outcomes import StepOutcome
from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode


def requested_day(
    call: CheckAvailabilityArguments,
    content: ConversationContent,
    today: date,
    caller_words: str,
    settled_days: set[date],
) -> date | DayQuestion | StepOutcome:
    """The day asked for; the question to ask when the weekday named does not match the date
    named; or the outcome to report when the words name no day, or none the caller said.

    `settled_days` were worked out from the caller's words earlier in the call and said by the
    code: "el mismo día" passed as the day the code said is that day."""
    day = _worked_out(call, content, today)
    if isinstance(day, StepOutcome):  # Words that name no day are answered first.
        return day
    if isinstance(day, date) and day in settled_days:
        return day
    heard = said_day(call, caller_words, content)
    if isinstance(heard, StepOutcome):  # The caller said none of it: the code asks the day.
        return heard
    return day if heard is call else _worked_out(heard, content, today)


def _worked_out(
    call: CheckAvailabilityArguments, content: ConversationContent, today: date
) -> date | DayQuestion | StepOutcome:
    briefing = content.booking_briefing
    named = NamedDay(call.weekday, call.day_number, call.month)
    weekdays, months = briefing.weekdays, briefing.months
    try:
        day = day_said(
            named,
            call.relative_day,
            call.next_week,
            weekdays=weekdays,
            months=months,
            today=today,
        )
        question = day_question(day, named, weekdays=weekdays, months=months, today=today)
    except UnknownNamedDayError as error:
        report_error(ErrorCode.TOOL_ARGUMENTS_INVALID, fields=",".join(error.fields))
        return StepOutcome({"status": "invalid_arguments", "fields": error.fields}, None)
    return day if question is None else question
