"""A fiber waiting for work on another thread waits through
``pyfect._os_wait.os_wait``, which keeps a timer pending while it waits.
A bare ``callback`` whose register hands work to a thread looks, to a
synchronous run's stall detection, like a fiber nothing can wake: a
``@testing.effect`` test failed ``fx.blocking`` work longer than a second
with ``StalledError`` (``tests/test_testing_harness.py``).

This walks the sources: no function passed to ``callback`` / ``_Callback``
may submit work to a thread pool, start a thread, or post to another loop.
"""

import ast
from pathlib import Path

_SOURCE = Path(__file__).parent.parent / "src" / "pyfect"
_HANDOFFS = {"submit", "run_coroutine_threadsafe", "call_soon_threadsafe", "Thread"}
_CALLBACKS = {"callback", "_Callback"}


def _called_name(call: ast.Call) -> str | None:
    match call.func:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def _handoffs(function: ast.AST) -> set[str]:
    return {
        name
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and (name := _called_name(node)) in _HANDOFFS
    }


def _offenders(path: Path, root: Path = _SOURCE) -> list[str]:
    offenders: list[str] = []

    def visit(node: ast.AST, scopes: list[dict[str, ast.AST]]) -> None:
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
            local: dict[str, ast.AST] = {
                child.name: child
                for child in node.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            }
            scopes = [*scopes, local]
        if isinstance(node, ast.Call) and _called_name(node) in _CALLBACKS and node.args:
            match node.args[0]:
                case ast.Lambda() as registered:
                    pass
                case ast.Name(id=name):
                    registered = next((s[name] for s in reversed(scopes) if name in s), None)
                case _:
                    registered = None
            if registered is not None and (found := _handoffs(registered)):
                where = f"{path.relative_to(root)}:{node.lineno}"
                offenders.append(f"{where} hands work to a thread ({sorted(found)})")
        for child in ast.iter_child_nodes(node):
            visit(child, scopes)

    visit(ast.parse(path.read_text()), [])
    return offenders


def test_callbacks_that_wait_on_another_thread_use_os_wait():
    offenders = [line for path in sorted(_SOURCE.rglob("*.py")) for line in _offenders(path)]
    assert offenders == []


def test_the_check_sees_a_bare_callback_waiting_on_a_thread(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def work():\n"
        "    def register(resume):\n"
        "        pool.submit(job).add_done_callback(lambda f: resume(f.result()))\n"
        "    return callback(register)\n"
    )
    assert _offenders(sample, tmp_path) == ["sample.py:4 hands work to a thread (['submit'])"]
