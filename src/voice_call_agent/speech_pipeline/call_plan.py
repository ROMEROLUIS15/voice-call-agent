"""What a call says and can do: its prompt, its greeting and, with a business, its booking flow.

A call whose business the backend resolved gets the booking prompt with that business's catalog
and the booking conversation as a Pipecat Flows graph, which says the business's greeting; any
other call gets the prompt that books nothing and the generic greeting (ADR 0019).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from voice_call_agent.booking_flow.booking_graph import BookingGraph
from voice_call_agent.booking_flow.booking_steps import BookingSteps
from voice_call_agent.call_session.session import CallSession
from voice_call_agent.conversation_content.business_briefing import booking_prompt
from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.observability.backend_timing import TimedSchedulingBackend
from voice_call_agent.observability.call_trace_recorder import CallTraceRecorder
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend
from voice_call_agent.write_guards.booking_guard import BookingGuard


@dataclass(frozen=True)
class CallPlan:
    system_prompt: str
    greeting: str
    """Said when the call connects; a booking flow says it in its first node instead."""
    booking_flow: BookingGraph | None


def plan_call(
    session: CallSession,
    *,
    content: ConversationContent,
    backend: SchedulingBackend | None,
    recorder: CallTraceRecorder,
    today_in: Callable[[str], date],
) -> CallPlan:
    """`today_in` gives today's date in a time zone: the business's, for "mañana" to be right."""
    business = session.business_context
    if backend is None or business is None or session.business_id is None:
        return CallPlan(
            system_prompt=content.system_prompt, greeting=content.greeting, booking_flow=None
        )
    today = today_in(business.timezone)
    # Each request the conversation makes lands in the call's trace with how long it took.
    backend = TimedSchedulingBackend(backend, recorder.record_backend_request)
    guard = BookingGuard(
        call_id=session.call_id,
        catalog=business.services,
        backend=backend,
        caller_turns=lambda: recorder.caller_turns,
        on_decision=recorder.record_write,
    )
    steps = BookingSteps(
        call_id=session.call_id,
        catalog=business.services,
        backend=backend,
        guard=guard,
        content=content,
        weekly_hours=business.weekly_hours,
        today=today,
    )
    role = booking_prompt(content, business, today)
    return CallPlan(
        system_prompt=role,
        greeting=business.greeting,
        booking_flow=BookingGraph(
            steps=steps, content=content, role=role, greeting=business.greeting
        ),
    )
