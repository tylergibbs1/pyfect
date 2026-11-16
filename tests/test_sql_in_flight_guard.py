"""A SQL test that asserts work it started is still in flight holds the SQL
loop while it does (``tests/oracle/_sql_loop.held``).

``pyfect.sql._loop.call`` resumes its fiber at once when the loop thread
settles the call before the fiber waits, so a fiber forked with
``start_immediately`` can be done before ``fork`` returns. On a loaded CI
runner ``test_pg_pin_release`` found its listener already subscribed
(``assert Success(value=<Queue>) is None``). This walks the tests: in a
file that uses ``pyfect.sql``, ``assert <fiber>.poll_unsafe() is None`` on a
fiber forked with ``start_immediately=True`` must sit inside
``with ...held():``.
"""

import ast
from pathlib import Path

_TESTS = Path(__file__).parent


def _forked_immediately(function: ast.AST) -> set[str]:
    """Names bound to something forked with ``start_immediately=True``."""
    names: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue
        immediate = any(
            isinstance(call, ast.Call)
            and any(
                k.arg == "start_immediately"
                and isinstance(k.value, ast.Constant)
                and k.value.value is True
                for k in call.keywords
            )
            for call in ast.walk(node.value)
        )
        if immediate:
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def _polled_none(node: ast.Assert) -> str | None:
    """``x`` of ``assert x.poll_unsafe() is None``."""
    match node.test:
        case ast.Compare(
            left=ast.Call(func=ast.Attribute(value=ast.Name(id=name), attr="poll_unsafe")),
            ops=[ast.Is()],
            comparators=[ast.Constant(value=None)],
        ):
            return name
        case _:
            return None


def _holds_loop(node: ast.With) -> bool:
    return any(
        isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, (ast.Name, ast.Attribute))
        and (
            item.context_expr.func.id
            if isinstance(item.context_expr.func, ast.Name)
            else item.context_expr.func.attr
        )
        == "held"
        for item in node.items
    )


def unheld_in_flight_checks(source: str) -> list[int]:
    """Lines asserting a ``start_immediately`` fork is still running outside
    a held SQL loop."""
    tree = ast.parse(source)
    found: list[int] = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        forked = _forked_immediately(function)

        def visit(node: ast.AST, held: bool, forked: set[str] = forked) -> None:
            if isinstance(node, ast.Assert) and not held and _polled_none(node) in forked:
                found.append(node.lineno)
            inner = held or (isinstance(node, ast.With) and _holds_loop(node))
            for child in ast.iter_child_nodes(node):
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit(child, inner)

        for statement in function.body:
            visit(statement, held=False)
    return found


def test_sql_tests_hold_the_loop_to_assert_work_in_flight() -> None:
    offenders: list[str] = []
    for path in sorted(_TESTS.rglob("*.py")):
        source = path.read_text()
        if "pyfect.sql" not in source:
            continue
        offenders += [
            f"{path.relative_to(_TESTS)}:{line}" for line in unheld_in_flight_checks(source)
        ]
    assert offenders == [], "start the work inside `with _sql_loop.held():`"


def test_the_guard_finds_an_unheld_check() -> None:
    source = (
        "def test():\n"
        "    f = yield from work.fork(start_immediately=True)\n"
        "    assert f.poll_unsafe() is None\n"
        "    with _sql_loop.held():\n"
        "        g = yield from work.fork(start_immediately=True)\n"
        "        assert g.poll_unsafe() is None\n"
    )
    assert unheld_in_flight_checks(source) == [3]
