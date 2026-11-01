"""Work handed to a thread or loop that a resource owns goes through
``Lifetime.submit`` (DOGFOOD trawl 2).

A service released with its layer can still be called through a value that
outlived it. Submitting to its stopped executor raised ``RuntimeError:
cannot schedule new futures after shutdown`` as a defect, and a coroutine
sent to its stopped loop waited forever. ``Lifetime.submit`` turns both into
a ``Released`` failure the service maps to its typed error; this walks the
source so no hand-off skips it.
"""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "pyfect"

ALLOWED = {
    "socket/_loop.py": "one loop per process, never stopped",
    "http/uvicorn_server.py": "the server's own loop, used only by its start and stop",
}


def _is_handoff(call: ast.Call) -> bool:
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name == "run_coroutine_threadsafe":
        return True
    # executor.submit on an executor the instance owns (self._executor, ...)
    return (
        name == "submit"
        and isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Attribute)
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "self"
        and not func.value.attr.endswith("lifetime")
    )


def _guarded(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Inside a lambda passed to ``<...>lifetime.submit(...)``."""
    current = node
    while current in parents:
        parent = parents[current]
        if isinstance(current, ast.Lambda) and isinstance(parent, ast.Call):
            func = parent.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "submit"
                and isinstance(func.value, ast.Attribute | ast.Name)
                and (func.value.attr if isinstance(func.value, ast.Attribute) else func.value.id)
                .lstrip("_")
                .endswith("lifetime")
            ):
                return True
        current = parent
    return False


def _unguarded() -> list[str]:
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        if relative in ALLOWED:
            continue
        tree = ast.parse(path.read_text())
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        found.extend(
            f"{relative}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _is_handoff(node) and not _guarded(node, parents)
        )
    return found


def test_every_handoff_to_an_owned_thread_or_loop_checks_its_lifetime() -> None:
    assert _unguarded() == [], (
        "hand work to a thread or loop a resource owns through Lifetime.submit "
        "(pyfect._released), so a use after release fails with a typed error"
    )


def test_the_check_sees_an_unguarded_handoff() -> None:
    source = "class A:\n    def go(self, f):\n        return self._executor.submit(f)\n"
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_handoff(n)]
    assert len(calls) == 1
    assert not _guarded(calls[0], parents)
    guarded = ast.parse("self._lifetime.submit(lambda: self._executor.submit(f))")
    parents = {child: node for node in ast.walk(guarded) for child in ast.iter_child_nodes(node)}
    calls = [n for n in ast.walk(guarded) if isinstance(n, ast.Call) and _is_handoff(n)]
    assert len(calls) == 1
    assert _guarded(calls[0], parents)
