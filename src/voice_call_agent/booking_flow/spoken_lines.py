"""The lines the code says on entering a node, as custom Flows actions (ADR 0019)."""

from collections.abc import Callable
from typing import Any, cast

from pipecat.flows import ActionConfig, FlowManager
from pipecat.frames.frames import TTSSpeakFrame


def say(text: str, *, before: Callable[[], None] | None = None) -> ActionConfig:
    """A line the code says on entering a node, before its task and functions apply.

    Not Flows' built-in `tts_say`: Flows applies the node only once that action's completion
    frame reaches the end of the pipeline, and a caller who speaks over the line drops the frame,
    so the node never applies and the model answers with the previous node's functions (Pipecat
    issue #5263, open in 1.14). A custom action is not waited for: the node applies at once and
    the line is still spoken, and kept in the context, as the caller hears it. `before` runs as
    the line is queued, such as watching whether the caller speaks over a read-back.
    """
    # Flows passes extra keys to the handler; its TypedDict does not declare them.
    action = {"type": "say", "handler": _speak, "text": text, "before": before}
    return cast(ActionConfig, action)


def joined(said: str, actions: list[ActionConfig]) -> list[ActionConfig]:
    """The code's result and the node's own lines as one line, so the caller hears one reply
    (the harness counts them too); what runs before any of them runs before it."""
    lines = [action for action in actions if action["type"] == "say"]
    befores = (cast(dict[str, Any], line).get("before") for line in lines)
    before = next((run for run in befores if run is not None), None)
    text = " ".join([said, *(line["text"] for line in lines)])
    return [say(text, before=before), *(action for action in actions if action["type"] != "say")]


async def _speak(action: dict[str, Any], flow_manager: FlowManager) -> None:
    if action.get("before") is not None:
        action["before"]()
    await flow_manager.worker.queue_frame(TTSSpeakFrame(text=action["text"]))
