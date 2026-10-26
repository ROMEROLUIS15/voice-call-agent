"""INV-8 · Isolated channel: outside the transports and the session, nothing knows the channel."""

import ast
from pathlib import Path

from tests.architecture.source_tree import is_composition_root, python_modules, relative_parts

CHANNEL_AWARE_PACKAGES = frozenset({"call_transports", "call_session", "settings"})
CHANNEL_NAMES = frozenset({"twilio", "whatsapp", "browser"})


def channel_leaks(source: str) -> list[str]:
    """Uses of the channel in a module: `.channel`, the `CallChannel` enum or a channel literal."""
    leaks = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr == "channel":
            leaks.append(f"line {node.lineno}: reads `.channel`")
        elif isinstance(node, ast.ImportFrom) and any(a.name == "CallChannel" for a in node.names):
            leaks.append(f"line {node.lineno}: imports `CallChannel`")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.lower() in CHANNEL_NAMES
        ):
            leaks.append(f"line {node.lineno}: literal {node.value!r}")
    return leaks


def _channel_agnostic_modules() -> list[Path]:
    return [
        path
        for path in python_modules()
        if relative_parts(path)[0] not in CHANNEL_AWARE_PACKAGES and not is_composition_root(path)
    ]


def test_engine_modules_do_not_know_the_channel() -> None:
    leaks = {
        "/".join(relative_parts(path)): found
        for path in _channel_agnostic_modules()
        if (found := channel_leaks(path.read_text(encoding="utf-8")))
    }
    assert leaks == {}


def test_checker_catches_each_kind_of_leak() -> None:
    # The test above is only worth something if the checker fails when INV-8 breaks.
    assert channel_leaks("if session.channel is not None: pass")
    assert channel_leaks("from voice_call_agent.call_session.session import CallChannel")
    assert channel_leaks("label = 'whatsapp'")
    assert channel_leaks("label = 'Twilio'")
    assert channel_leaks("label = 'browser'")
    assert channel_leaks('"""A docstring that mentions Twilio in a sentence."""') == []
