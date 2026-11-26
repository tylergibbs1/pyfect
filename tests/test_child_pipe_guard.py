"""Every child a test or script starts with ``stdout=PIPE`` or ``stderr=PIPE`` has that pipe read.

A pipe holds a few pages. A child that writes more than that to a pipe nobody reads blocks in
the write, so a test that reads the output only after the child exits waits for it forever: a
dogfood app's server logged 14 KB, which fit a macOS pipe and filled a Linux one, and its test
hung on Linux only. So a ``subprocess.Popen`` or ``asyncio.create_subprocess_*`` in ``tests/``
or ``scripts/`` that pipes stdout or stderr must, in the function that holds the handle (the
class, for ``self.<name>``), call its ``communicate()`` or use the pipe itself: read it, iterate
it, or hand it to a reader thread. A reference in a comparison (``assert proc.stdout is not
None``) reads nothing. Write output nobody reads to a file or ``DEVNULL`` instead.

A handle that leaves the function (returned, put in a list) can't be followed: read its pipes
where it is made, or list the function in ``ALLOWED`` with where its pipes are read.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import _source
import pytest

_SPAWNS = frozenset({"Popen", "create_subprocess_exec", "create_subprocess_shell"})
_STREAMS = ("stdout", "stderr")
_ROOTS = (_source.TESTS, _source.ROOT / "scripts")

ALLOWED: dict[str, str] = {}
"""``<path>::<function>`` of a spawn whose handle leaves the function, with where the pipes
it leaves piped are read."""

type _Scope = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Module


def _named(node: ast.expr, names: frozenset[str]) -> bool:
    return (isinstance(node, ast.Name) and node.id in names) or (
        isinstance(node, ast.Attribute) and node.attr in names
    )


def _piped(call: ast.Call) -> tuple[str, ...]:
    """The streams the spawn pipes to the parent; ``stderr=STDOUT`` goes with stdout."""
    given = {keyword.arg: keyword.value for keyword in call.keywords}
    return tuple(s for s in _STREAMS if s in given and _named(given[s], frozenset({"PIPE"})))


def _parents(module: ast.Module) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(module) for child in ast.iter_child_nodes(node)}


def _enclosing(node: ast.AST, parents: dict[ast.AST, ast.AST], *, cls: bool) -> _Scope:
    """The function (or module) around ``node``; with ``cls``, the class."""
    while True:
        node = parents[node]
        if isinstance(node, ast.ClassDef if cls else ast.FunctionDef | ast.AsyncFunctionDef):
            return node
        if isinstance(node, ast.Module):
            return node


def _handle(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> tuple[_Scope, str] | None:
    """Where the spawn's handle is held (``x = ...``, ``with ... as x``, ``self.x = ...``), and
    its spelling; ``None`` when it leaves the function."""
    node, parent = call, parents[call]
    if isinstance(parent, ast.Await):
        node, parent = parent, parents[parent]
    if isinstance(parent, ast.Assign) and len(parent.targets) == 1:
        target = parent.targets[0]
    elif isinstance(parent, ast.AnnAssign | ast.withitem):
        target = parent.target if isinstance(parent, ast.AnnAssign) else parent.optional_vars
    else:
        return None
    if isinstance(target, ast.Name):
        return _enclosing(node, parents, cls=False), target.id
    if isinstance(target, ast.Attribute) and _named(target.value, frozenset({"self"})):
        return _enclosing(node, parents, cls=True), ast.unparse(target)
    return None


def _read(scope: _Scope, handle: str, parents: dict[ast.AST, ast.AST]) -> set[str]:
    """The streams of ``handle`` that ``scope`` reads: all after ``communicate``."""
    found: set[str] = set()
    for node in ast.walk(scope):
        if not isinstance(node, ast.Attribute) or ast.unparse(node.value) != handle:
            continue
        if node.attr == "communicate":
            found.update(_STREAMS)
        elif node.attr in _STREAMS and not isinstance(parents[node], ast.Compare):
            found.add(node.attr)
    return found


def _function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    while node in parents and not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        node = parents[node]
    return getattr(node, "name", "<module>")


def unread_pipes(module: ast.Module, where: str) -> Iterator[str]:
    """Each spawn in ``module`` with a piped stream nothing reads, as ``where:line: ...``."""
    parents = _parents(module)
    for call in ast.walk(module):
        if not isinstance(call, ast.Call) or not _named(call.func, _SPAWNS):
            continue
        piped = _piped(call)
        if not piped:
            continue
        held = _handle(call, parents)
        if held is None:
            if f"{where}::{_function(call, parents)}" not in ALLOWED:
                yield (
                    f"{where}:{call.lineno}: the handle of a spawn piping {' and '.join(piped)} "
                    "leaves the function: read the pipes here, or list it in ALLOWED"
                )
            continue
        scope, handle = held
        for stream in sorted(set(piped) - _read(scope, handle, parents)):
            yield (
                f"{where}:{call.lineno}: {handle}.{stream} is piped and never read: "
                "communicate(), read it in a thread, or write it to a file"
            )


def _files() -> Iterator[Path]:
    for root in _ROOTS:
        for path in _source.files(root):
            if _source.mentions(path, *_SPAWNS):
                yield path


def test_every_piped_child_output_is_read() -> None:
    found = [
        hit
        for path in _files()
        for hit in unread_pipes(_source.tree(path), path.relative_to(_source.ROOT).as_posix())
    ]
    assert found == [], "\n".join(found)


def test_every_allowed_spawn_still_hands_its_handle_on() -> None:
    spawns = {
        f"{path.relative_to(_source.ROOT).as_posix()}::{name}"
        for path in _files()
        for name in _handed_on(_source.tree(path))
    }
    assert sorted(set(ALLOWED) - spawns) == []


def _handed_on(module: ast.Module) -> Iterator[str]:
    parents = _parents(module)
    for call in ast.walk(module):
        if (
            isinstance(call, ast.Call)
            and _named(call.func, _SPAWNS)
            and _piped(call)
            and _handle(call, parents) is None
        ):
            yield _function(call, parents)


def _hits(source: str) -> list[str]:
    module = _source.parse(source)
    assert isinstance(module, ast.Module)
    return [hit.split(": ", 1)[1] for hit in unread_pipes(module, "t.py")]


_UNREAD = {
    # The dogfood app's hang: the output is read only once the server has exited.
    "wait": """
def f():
    p = subprocess.Popen(a, stdout=subprocess.PIPE)
    p.wait()
""",
    # Only stdout is read; a chatty stderr still fills its pipe.
    "stderr": """
def f():
    with Popen(a, stdout=PIPE, stderr=PIPE) as p:
        for line in p.stdout:
            pass
""",
    # A check that the pipe exists reads nothing.
    "compare": """
def f():
    p = Popen(a, stderr=PIPE)
    assert p.stderr is not None
    p.wait()
""",
    "class": """
class C:
    def __init__(self):
        self.p = Popen(a, stdout=PIPE)

    def close(self):
        self.p.wait()
""",
    "asyncio": """
async def f():
    p = await asyncio.create_subprocess_exec(a, stdout=PIPE)
    await p.wait()
""",
    "returned": """
def f():
    return Popen(a, stdout=PIPE)
""",
}

_READ = {
    "communicate": """
def f():
    p = Popen(a, stdout=PIPE, stderr=PIPE)
    p.communicate(timeout=5)
""",
    "merged": """
def f():
    with Popen(a, stdout=PIPE, stderr=STDOUT) as p:
        for line in p.stdout:
            pass
""",
    "thread": """
def f():
    p = Popen(a, stdout=PIPE)
    threading.Thread(target=read, args=(p.stdout,)).start()
    p.wait()
""",
    "class": """
class C:
    def __init__(self):
        self.p = Popen(a, stdin=PIPE, stdout=PIPE)

    def ask(self):
        return self.p.stdout.readline()
""",
    "file": """
def f(log):
    p = Popen(a, stdout=log, stderr=DEVNULL)
    p.wait()
""",
    "stdin": """
def f():
    return Popen(a, stdin=PIPE)
""",
}


@pytest.mark.parametrize("source", _UNREAD.values(), ids=_UNREAD.keys())
def test_an_unread_pipe_is_found(source: str) -> None:
    assert len(_hits(source)) == 1, source


@pytest.mark.parametrize("source", _READ.values(), ids=_READ.keys())
def test_a_read_pipe_passes(source: str) -> None:
    assert _hits(source) == []
