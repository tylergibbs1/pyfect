"""A fiber waiting for work on another thread waits through
``pyfect._os_wait.os_wait``, which keeps a timer pending while it waits.
A bare ``callback`` whose register hands work to a thread looks, to a
synchronous run's stall detection, like a fiber nothing can wake: a
``@testing.effect`` test failed ``fx.blocking`` work longer than a second
with ``StalledError`` (``tests/test_testing_harness.py``).

An ``os_wait`` says what it waits for. Work it hands to a thread is
``waits_for="work"``: ``TestClock.adjust`` waits for it, so a loop of a
SQLite write then a sleep runs once per adjust (DOGFOOD beacon #9). Marked
``"event"``, the clock would move on while the thread still runs.

This walks the sources: no function passed to ``callback`` / ``_Callback``
may submit work to a thread pool, start a thread, or post to another loop,
and one passed to ``os_wait`` that does must say ``waits_for="work"``.
"""

import ast
from pathlib import Path

_SOURCE = Path(__file__).parent.parent / "src" / "pyfect"
_HANDOFFS = {
    "submit",
    "run_coroutine_threadsafe",
    "call_soon_threadsafe",
    "call_soon",
    "run_in_executor",
    "Thread",
}
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


def _required_waits_for(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """The parameters of ``function`` typed ``WaitsFor`` with no default:
    each caller says what the wait is."""
    args = function.args
    positional = [*args.posonlyargs, *args.args]
    defaulted = {a.arg for a in positional[len(positional) - len(args.defaults) :]}
    defaulted |= {
        a.arg for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True) if d is not None
    }
    return {
        a.arg
        for a in [*positional, *args.kwonlyargs]
        if isinstance(a.annotation, ast.Name)
        and a.annotation.id == "WaitsFor"
        and a.arg not in defaulted
    }


def _waits_for_an_event(call: ast.Call, required: set[str]) -> bool:
    """A bare callback, or an ``os_wait`` neither marked ``waits_for="work"``
    nor passing on a required ``WaitsFor`` parameter (``required``)."""
    name = _called_name(call)
    if name in _CALLBACKS:
        return True
    if name != "os_wait":
        return False
    marked = next((k.value for k in call.keywords if k.arg == "waits_for"), None)
    if isinstance(marked, ast.Name) and marked.id in required:
        return False
    return not (isinstance(marked, ast.Constant) and marked.value == "work")


def _offenders(path: Path, root: Path = _SOURCE) -> list[str]:
    offenders: list[str] = []

    def visit(node: ast.AST, scopes: list[dict[str, ast.AST]], required: set[str]) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            required = _required_waits_for(node)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
            local: dict[str, ast.AST] = {
                child.name: child
                for child in node.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            }
            scopes = [*scopes, local]
        if isinstance(node, ast.Call) and _waits_for_an_event(node, required) and node.args:
            match node.args[0]:
                case ast.Lambda() as registered:
                    pass
                case ast.Name(id=name):
                    registered = next((s[name] for s in reversed(scopes) if name in s), None)
                case _:
                    registered = None
            if registered is not None and (found := _handoffs(registered)):
                where = f"{path.relative_to(root)}:{node.lineno}"
                kind = "a thread" if _called_name(node) in _CALLBACKS else "a thread as an event"
                offenders.append(f"{where} hands work to {kind} ({sorted(found)})")
        for child in ast.iter_child_nodes(node):
            visit(child, scopes, required)

    visit(ast.parse(path.read_text()), [], set())
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


def test_the_check_sees_thread_work_waited_for_as_an_event(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def work():\n"
        "    def register(resume):\n"
        "        pool.submit(job).add_done_callback(lambda f: resume(f.result()))\n"
        "    return os_wait(register, waits_for='event')\n"
        "def fine():\n"
        "    def register(resume):\n"
        "        pool.submit(job).add_done_callback(lambda f: resume(f.result()))\n"
        "    return os_wait(register, waits_for='work')\n"
    )
    assert _offenders(sample, tmp_path) == [
        "sample.py:4 hands work to a thread as an event (['submit'])"
    ]


def test_the_check_lets_a_required_waits_for_parameter_pass_through(tmp_path: Path):
    """A wrapper whose callers each say what they wait for (a required
    ``waits_for: WaitsFor``, as redis-py's loop ``run``) passes it on; one
    with a default, or not typed ``WaitsFor``, still decides it itself."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def run(job, *, waits_for: WaitsFor):\n"
        "    def register(resume):\n"
        "        pool.submit(job).add_done_callback(lambda f: resume(f.result()))\n"
        "    return os_wait(register, waits_for=waits_for)\n"
        "def defaulted(job, *, waits_for: WaitsFor = 'event'):\n"
        "    def register(resume):\n"
        "        pool.submit(job).add_done_callback(lambda f: resume(f.result()))\n"
        "    return os_wait(register, waits_for=waits_for)\n"
    )
    assert _offenders(sample, tmp_path) == [
        "sample.py:8 hands work to a thread as an event (['submit'])"
    ]
