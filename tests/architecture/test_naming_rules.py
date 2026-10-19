"""Naming convention (constitution: naming) and dependency direction, checked on the source."""

import ast
import re
from pathlib import Path

from tests.architecture.source_tree import (
    EVALS_ROOT,
    all_source_files,
    evals_modules,
    is_composition_root,
    python_modules,
    relative_parts,
    repository_path,
)

BANNED_MODULE_NAMES = frozenset(
    {
        "utils",
        "util",
        "helpers",
        "helper",
        "common",
        "misc",
        "core",
        "manager",
        "managers",
        "handler",
        "handlers",
        "data",
        "service",
        "services",
        "client",
    }
)
BANNED_IDENTIFIER_WORDS = frozenset(
    {"util", "utils", "helper", "helpers", "manager", "handler", "misc"}
)
SCHEDULING_ADAPTER = ("adapters", "cronix_scheduling_api")


def banned_module_names(parts: tuple[str, ...]) -> list[str]:
    """Package or module names in the path that say nothing about what the code does."""
    names = [*parts[:-1], Path(parts[-1]).stem]
    return [name for name in names if name in BANNED_MODULE_NAMES]


def banned_identifiers(source: str) -> list[str]:
    """Classes and functions whose name contains a banned word."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            words = {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", node.name)}
            if words & BANNED_IDENTIFIER_WORDS:
                found.append(node.name)
    return found


def mentions_cronix(text: str) -> bool:
    return "cronix" in text.lower()


def adapter_imports(source: str) -> list[str]:
    """Imports of concrete adapters: the domain must depend on protocols instead."""
    imported = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "voice_call_agent.adapters"
        ):
            imported.append(node.module or "")
        elif isinstance(node, ast.Import):
            imported += [
                a.name for a in node.names if a.name.startswith("voice_call_agent.adapters")
            ]
    return imported


def test_no_generic_module_names() -> None:
    offenders = {
        "/".join(parts): names
        for path in python_modules()
        if (names := banned_module_names(parts := relative_parts(path)))
    }
    assert offenders == {}


def test_no_generic_class_or_function_names() -> None:
    offenders = {
        "/".join(relative_parts(path)): names
        for path in python_modules()
        if (names := banned_identifiers(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}


def test_the_evals_follow_the_same_naming_rules() -> None:
    offenders = {
        repository_path(path): names
        for path in evals_modules()
        if (
            names := banned_module_names(path.relative_to(EVALS_ROOT).parts)
            + banned_identifiers(path.read_text(encoding="utf-8"))
        )
    }
    assert offenders == {}


def test_cronix_appears_only_in_its_adapter_and_the_composition_root() -> None:
    offenders = [
        "/".join(parts)
        for path in all_source_files()
        if (parts := relative_parts(path))[:2] != SCHEDULING_ADAPTER
        and not is_composition_root(path)
        and (mentions_cronix(str(Path(*parts))) or mentions_cronix(_read(path)))
    ]
    assert offenders == []


def test_only_adapters_and_the_composition_root_import_adapters() -> None:
    offenders = {
        "/".join(parts): imported
        for path in python_modules()
        if (parts := relative_parts(path))[0] != "adapters"
        and not is_composition_root(path)
        and (imported := adapter_imports(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}


def test_checkers_catch_each_violation() -> None:
    # The tests above are only worth something if each checker fails when its rule breaks.
    assert banned_module_names(("speech_pipeline", "utils.py")) == ["utils"]
    assert banned_module_names(("helpers", "phone.py")) == ["helpers"]
    assert banned_module_names(("speech_pipeline", "service_factories.py")) == []
    assert banned_identifiers("class CallManager: pass") == ["CallManager"]
    assert banned_identifiers("def webhook_handler(): pass") == ["webhook_handler"]
    assert banned_identifiers("class CallSupervisor: pass") == []
    assert mentions_cronix("from x import CronixClient")
    assert adapter_imports("from voice_call_agent.adapters.deepgram_speech import x")
    assert adapter_imports("import voice_call_agent.adapters.cronix_scheduling_api")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""
