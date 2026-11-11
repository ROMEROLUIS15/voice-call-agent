"""The day a caller asked for, worked out by the code from their words, never the model's date
(ADR 0019): a weekday, a day number and a month, or today, tomorrow and the day after."""

from datetime import date

from voice_call_agent.booking_flow.flow_arguments import CheckAvailabilityArguments
from voice_call_agent.booking_flow.named_day import (
    DayQuestion,
    NamedDay,
    UnknownNamedDayError,
    day_question,
    day_said,
)
from voice_call_agent.booking_flow.step_outcomes import StepOutcome
from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode


def requested_day(
    call: CheckAvailabilityArguments, content: ConversationContent, today: date
) -> date | DayQuestion | StepOutcome:
    """The day asked for; the question to ask when the weekday named does not match the date
    named; or the outcome to report when the words name no day."""
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
