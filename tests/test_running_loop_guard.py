"""Code a fiber runs must find its asyncio loop through ``_root.run_loop()``
(the loop driving the fiber's run), never ``asyncio.get_running_loop()``:
under ``run_sync`` inside a coroutine, the running loop is blocked until
``run_sync`` returns, and work put on it hangs the program
(``tests/test_run_sync_in_loop.py``).

A coroutine may ask for its running loop. A plain function may only where
it is listed below, with why it never runs on a fiber of a ``run_sync``
run."""

import ast
from pathlib import Path

_SOURCE = Path(__file__).parent.parent / "src" / "pyfect"

_ALLOWED: dict[tuple[str, str], str] = {
    ("_root.py", "ambient_run"): "asks only when no fiber is running on this thread",
    ("_root.py", "loop_running_here"): "the helper that answers whether a loop runs here",
    ("scheduler.py", "current"): "AsyncioScheduler.current, called by run_async",
    ("_fiber_collections.py", "future_of"): "the run_promise APIs, called from a coroutine",
    ("managed_runtime.py", "_loop_scheduler"): "called once a loop is known to run here",
    ("run.py", "_interrupt_on_signals"): "run_main's own loop",
    ("http/web_handler.py", "_handle"): "the web handler, called by the server's coroutine",
    ("http/wire.py", "_cancel"): "closes a body on the loop if there is one, else runs it",
    ("http/asgi/_http.py", "__init__"): "made by the ASGI coroutine on the server's loop",
    ("http/asgi/_mount.py", "__init__"): "made by the ASGI coroutine on the server's loop",
    ("http/asgi/_web_socket.py", "__init__"): "made by the ASGI coroutine on the server's loop",
    ("socket/_tls_session.py", "__init__"): "runs on the socket module's own loop thread",
    ("sql/pg/_session.py", "_start_pump"): "runs on the driver's own loop thread",
}


def _plain_function_calls() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in _SOURCE.rglob("*.py"):
        name = path.relative_to(_SOURCE).as_posix()

        def visit(node: ast.AST, function: ast.AST | None, name: str = name) -> None:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                function = node
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get_running_loop"
                and not isinstance(function, ast.AsyncFunctionDef)
            ):
                found.add((name, getattr(function, "name", "<lambda or module>")))
            for child in ast.iter_child_nodes(node):
                visit(child, function)

        visit(ast.parse(path.read_text()), None)
    return found


def test_plain_functions_ask_for_the_running_loop_only_where_listed():
    assert _plain_function_calls() - _ALLOWED.keys() == set()


def test_the_list_has_no_stale_entries():
    assert _ALLOWED.keys() - _plain_function_calls() == set()
