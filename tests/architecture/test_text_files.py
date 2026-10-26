"""Text files carry no stray control or invisible characters.

A mistyped escape such as `\\v` in a path becomes a control character; an escape
such as `\\uFE0F` decoded on the way into a file becomes an invisible one.
"""

import unicodedata
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = frozenset(
    {".md", ".py", ".toml", ".yml", ".yaml", ".example", ".txt", ".json", ".ambr", ".html", ".js"}
)
SKIPPED_DIRECTORIES = frozenset({".venv", ".git", "__pycache__", ".mypy_cache", ".ruff_cache"})
ALLOWED_CONTROL_CHARACTERS = frozenset({"\t", "\n"})


INVISIBLE_CATEGORIES = frozenset({"Cf", "Co", "Cs"})
"""Format (zero-width, direction marks), private-use and surrogate characters."""
VARIATION_SELECTORS = range(0xFE00, 0xFE10)


def control_characters(text: str) -> set[str]:
    return {c for c in text if ord(c) < 32 and c not in ALLOWED_CONTROL_CHARACTERS}


def invisible_characters(text: str) -> set[str]:
    return {
        c
        for c in text
        if unicodedata.category(c) in INVISIBLE_CATEGORIES or ord(c) in VARIATION_SELECTORS
    }


def _text_files() -> list[Path]:
    return [
        path
        for path in REPOSITORY_ROOT.rglob("*")
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and not SKIPPED_DIRECTORIES & set(path.relative_to(REPOSITORY_ROOT).parts)
    ]


def test_text_files_have_no_control_or_invisible_characters() -> None:
    offenders = {
        str(path.relative_to(REPOSITORY_ROOT)): sorted(hex(ord(c)) for c in found)
        for path in _text_files()
        if (found := control_characters(text := path.read_text(encoding="utf-8")))
        or (found := invisible_characters(text))
    }
    assert offenders == {}


def test_checker_catches_a_vertical_tab() -> None:
    assert control_characters("var" + chr(11) + "oice.log") == {chr(11)}
    assert control_characters("line\twith tab\n") == set()


def test_checker_catches_invisible_characters() -> None:
    assert invisible_characters("emoji" + chr(0xFE0F)) == {chr(0xFE0F)}
    assert invisible_characters("zero" + chr(0x200B) + "width") == {chr(0x200B)}
    assert invisible_characters("acentos: á é ñ ¿¡ —") == set()
