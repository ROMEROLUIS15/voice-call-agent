"""What a call says and can do: its prompt, its greeting and, with a business, its booking tools.

A call whose business the backend resolved gets the booking prompt with that business's catalog,
its greeting and the booking tools; any other call gets the prompt that books nothing.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from voice_call_agent.agent_tools.booking_tools import BookingTools
from voice_call_agent.call_session.session import CallSession
from voice_call_agent.conversation_content.business_briefing import booking_prompt
from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.observability.call_trace_recorder import CallTraceRecorder
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend
from voice_call_agent.speech_pipeline.pipeline_assembly import AgentTools
from voice_call_agent.write_guards.booking_guard import BookingGuard


@dataclass(frozen=True)
class CallPlan:
    system_prompt: str
    greeting: str
    tools: AgentTools | None


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
        return CallPlan(system_prompt=content.system_prompt, greeting=content.greeting, tools=None)
    guard = BookingGuard(
        call_id=session.call_id,
        catalog=business.services,
        backend=backend,
        caller_turns=lambda: recorder.caller_turns,
        on_decision=recorder.record_write,
    )
    return CallPlan(
        system_prompt=booking_prompt(content, business, today_in(business.timezone)),
        greeting=business.greeting,
        tools=BookingTools(call_id=session.call_id, backend=backend, guard=guard),
    )
