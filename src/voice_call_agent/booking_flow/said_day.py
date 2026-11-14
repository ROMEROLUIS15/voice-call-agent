"""Whether the caller said the day the model passes (ADR 0019).

The model passes the caller's words for the day and the code works the date out; a model that
writes the caller's next turn into its own reply ("userEl martes") would pass words the caller
never said. Each day field is looked up in what the caller said in the call: a field they did not
say is left out of a day they did say (a weekday the model worked out for a date said), and when
they said none, the code asks for the day instead of checking one. A month passed with a day
number the caller said is kept ("el 26 del mes que viene"), and a day the code already worked out
from the caller's words and said is accepted as it is (`requested_day`).
"""

import re
import unicodedata

from voice_call_agent.booking_flow.flow_arguments import CheckAvailabilityArguments
from voice_call_agent.booking_flow.step_outcomes import Step, StepOutcome
from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode

_DAY_FIELDS = ("relative_day", "weekday", "day_number", "month")


def said_day(
    call: CheckAvailabilityArguments, caller_words: str, content: ConversationContent
) -> CheckAvailabilityArguments | StepOutcome:
    """The arguments with only the day fields the caller said, or the outcome that asks for the
    day when they said none of those passed."""
    given = [field for field in _DAY_FIELDS if getattr(call, field) is not None]
    heard = f" {_plain(caller_words)} "
    unsaid = [field for field in given if not _said(call, field, heard, content)]
    if "day_number" in given and "day_number" not in unsaid and "month" in unsaid:
        unsaid.remove("month")  # "El 26 del mes que viene": a month alone invents no day.
    if not unsaid:
        return call
    if len(unsaid) == len(given):
        report_error(ErrorCode.DAY_NOT_SAID, fields=",".join(unsaid))
        return StepOutcome({"status": "day_not_said"}, Step.REQUEST, content.day_not_said)
    return call.model_copy(update=dict.fromkeys(unsaid))


def _said(
    call: CheckAvailabilityArguments, field: str, heard: str, content: ConversationContent
) -> bool:
    briefing = content.booking_briefing
    if field == "day_number" and call.day_number is not None:
        number = call.day_number
        words = [str(number), content.spoken_moments.numbers[number]]
        words += [briefing.first_of_month] if number == 1 else []
    elif field == "relative_day" and call.relative_day is not None:
        phrases = briefing.relative_days.get(call.relative_day.strip().casefold())
        if phrases is None:  # Not a day the code knows: the day's own check answers it.
            return True
        words = list(phrases)
    else:
        words = [str(getattr(call, field))]
    return any(f" {_plain(word)} " in heard for word in words)


def _plain(text: str) -> str:
    """Lowercase words without accents or punctuation, one space apart."""
    unaccented = unicodedata.normalize("NFD", text.casefold())
    letters = "".join(char for char in unaccented if not unicodedata.combining(char))
    return " ".join(re.findall(r"\w+", letters))
