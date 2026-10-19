"""Text files carry no stray control characters (a mistyped escape such as `\\v` in a path)."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = frozenset({".md", ".py", ".toml", ".yml", ".yaml", ".example", ".txt"})
SKIPPED_DIRECTORIES = frozenset({".venv", ".git", "__pycache__", ".mypy_cache", ".ruff_cache"})
ALLOWED_CONTROL_CHARACTERS = frozenset({"\t", "\n"})


def control_characters(text: str) -> set[str]:
    return {c for c in text if ord(c) < 32 and c not in ALLOWED_CONTROL_CHARACTERS}


def _text_files() -> list[Path]:
    return [
        path
        for path in REPOSITORY_ROOT.rglob("*")
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and not SKIPPED_DIRECTORIES & set(path.relative_to(REPOSITORY_ROOT).parts)
    ]


def test_text_files_have_no_control_characters() -> None:
    offenders = {
        str(path.relative_to(REPOSITORY_ROOT)): sorted(hex(ord(c)) for c in found)
        for path in _text_files()
        if (found := control_characters(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}


def test_checker_catches_a_vertical_tab() -> None:
    assert control_characters("var" + chr(11) + "oice.log") == {chr(11)}
    assert control_characters("line\twith tab\n") == set()
