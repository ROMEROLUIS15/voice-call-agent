"""No `except` silences an error: it re-raises, reports it with a code, or says why it is none."""

import ast

from tests.architecture.source_tree import python_modules, relative_parts

NOT_AN_ERROR_MARKER = "# not an error:"


def silent_handlers(source: str) -> list[int]:
    """Lines of handlers that neither raise, call `report_error`, nor carry the marker."""
    lines = source.splitlines()
    silent = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if NOT_AN_ERROR_MARKER in lines[node.lineno - 1]:
            continue
        body = [inner for statement in node.body for inner in ast.walk(statement)]
        raises = any(isinstance(inner, ast.Raise) for inner in body)
        reports = any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "report_error"
            for inner in body
        )
        if not (raises or reports):
            silent.append(node.lineno)
    return silent


def test_no_handler_silences_an_error() -> None:
    offenders = {
        "/".join(relative_parts(path)): lines
        for path in python_modules()
        if (lines := silent_handlers(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}


def test_checker_catches_a_silent_handler() -> None:
    assert silent_handlers("try:\n    x()\nexcept ValueError:\n    pass\n") == [3]
    assert silent_handlers("try:\n    x()\nexcept ValueError:\n    logger.warning('x')\n") == [3]
    assert (
        silent_handlers("try:\n    x()\nexcept ValueError as e:\n    raise Other() from e\n") == []
    )
    reported = "try:\n    x()\nexcept ValueError as e:\n    report_error(ErrorCode.X, error=e)\n"
    assert silent_handlers(reported) == []
    marked = "try:\n    x()\nexcept KeyError:  # not an error: optional key\n    y = 1\n"
    assert silent_handlers(marked) == []
