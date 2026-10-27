"""The call as it happened: the agent's lines and the caller's turns, in order.

An agent line is not always the answer to one caller turn: the agent may say something, call a
tool and speak again, and each model response becomes its own line. So the order comes from
when each caller turn was said, not from pairing lines and turns by position.
"""

from dataclasses import dataclass
from typing import Literal

from evals.conversation_harness.scripted_speech import RecordedToolCall

type Speaker = Literal["user", "assistant"]


@dataclass(frozen=True)
class SpokenTurn:
    """One turn of the call: what was said and, for the agent, the tools it called before."""

    role: Speaker
    text: str
    tool_calls: tuple[RecordedToolCall, ...] = ()


def call_transcript(
    agent_lines: list[str],
    tool_calls: dict[int, tuple[RecordedToolCall, ...]],
    caller_turns: list[tuple[int, str]],
) -> tuple[SpokenTurn, ...]:
    """Interleave the agent's lines and the caller's turns.

    `tool_calls` are keyed by the index of the line spoken after them; `caller_turns` are
    `(lines spoken before the turn, what the caller said)`, in order. Tools with nothing spoken
    after them close the call as a turn of the agent that says nothing.
    """
    turns: list[SpokenTurn] = []
    pending = iter(caller_turns)
    caller = next(pending, None)
    for index in range(len(agent_lines) + 1):
        while caller is not None and caller[0] <= index:
            turns.append(SpokenTurn("user", caller[1]))
            caller = next(pending, None)
        calls = tool_calls.get(index, ())
        if index < len(agent_lines):
            turns.append(SpokenTurn("assistant", agent_lines[index], calls))
        elif calls:
            turns.append(SpokenTurn("assistant", "", calls))
    return tuple(turns)
