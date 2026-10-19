"""The package's source files, classified by the role their location gives them."""

from pathlib import Path

import evals
import voice_call_agent

PACKAGE_ROOT = Path(voice_call_agent.__file__).parent
EVALS_ROOT = Path(evals.__file__).parent
REPOSITORY_ROOT = EVALS_ROOT.parent

# Composition root: picks and wires concrete components; decides nothing per call.
COMPOSITION_ROOT = frozenset({("__main__.py",), ("asgi_app.py",), ("service_composition.py",)})


def relative_parts(path: Path) -> tuple[str, ...]:
    return path.relative_to(PACKAGE_ROOT).parts


def python_modules() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def evals_modules() -> list[Path]:
    """The evaluation code: not shipped, but held to the same size and naming rules."""
    return sorted(EVALS_ROOT.rglob("*.py"))


def repository_path(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()


def all_source_files() -> list[Path]:
    """Python modules and the resource files shipped with them."""
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )


def is_composition_root(path: Path) -> bool:
    return relative_parts(path) in COMPOSITION_ROOT
