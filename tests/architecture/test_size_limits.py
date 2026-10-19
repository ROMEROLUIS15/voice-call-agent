"""Hard size limits of constitution §1: files ≤ ~300 lines, functions ≤ ~50 lines."""

import ast

from tests.architecture.source_tree import python_modules, relative_parts

MAX_FILE_LINES = 300
MAX_FUNCTION_LINES = 50


def long_functions(source: str) -> list[str]:
    """Functions longer than the limit, counting from the `def` line to the last statement."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            if length > MAX_FUNCTION_LINES:
                found.append(f"{node.name} ({length} lines)")
    return found


def test_files_stay_within_the_limit() -> None:
    long_files = {
        "/".join(relative_parts(path)): lines
        for path in python_modules()
        if (lines := len(path.read_text(encoding="utf-8").splitlines())) > MAX_FILE_LINES
    }
    assert long_files == {}


def test_functions_stay_within_the_limit() -> None:
    offenders = {
        "/".join(relative_parts(path)): found
        for path in python_modules()
        if (found := long_functions(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}


def test_checker_catches_a_long_function() -> None:
    body = "\n".join(f"    x{i} = {i}" for i in range(MAX_FUNCTION_LINES))
    assert long_functions(f"def too_long() -> None:\n{body}\n") == ["too_long (51 lines)"]
