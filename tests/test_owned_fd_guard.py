"""Work handed to another thread reaches a descriptor only through ``OwnedFd``.

A descriptor's number is reused once it is closed, so work on another thread
(the blocking pool, a thread of its own, the socket or server loop) that took
the number before a close and calls the system after it reaches whatever took
it (``tests/test_closing_descriptors_in_use.py``). ``pyfect._owned_fd.OwnedFd``
keeps the number taken while work uses it.

This walks the sources. A thunk is a lambda, a nested function or a method
given to something that runs it on another thread (``_HANDOFFS``), and the
methods it calls on ``self``. In a thunk:

- a descriptor or socket from outside it (a name or attribute ending in ``fd``
  or ``sock``) is only the owner of ``.use``, ``.using`` or
  ``.close_when_unused``;
- an ``os`` call taking a descriptor takes one the thunk was given (its own
  parameter or local name), as ``owned.use(lambda fd: os.write(fd, data))``.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import _source

_SOURCE = _source.SRC
_HANDOFFS = frozenset(
    {
        "blocking",
        "try_blocking",
        "run",  # file_system._errors.run: try_blocking with the error mapped
        "_in_thread",
        "submit",
        "run_in_executor",
        "to_thread",
        "Thread",
        "call_soon",
        "call_soon_threadsafe",
    }
)
_OWNED = frozenset({"use", "using", "close_when_unused"})
_DESCRIPTOR = re.compile(r"(^|_)(fd|sock)$")
_OS_TAKING_A_DESCRIPTOR = frozenset(
    {
        "close",
        "dup",
        "dup2",
        "fchmod",
        "fchown",
        "fdatasync",
        "fstat",
        "fstatvfs",
        "fsync",
        "ftruncate",
        "get_blocking",
        "lockf",
        "lseek",
        "posix_fadvise",
        "posix_fallocate",
        "pread",
        "preadv",
        "pwrite",
        "pwritev",
        "read",
        "readv",
        "sendfile",
        "set_blocking",
        "write",
        "writev",
    }
)

type _Function = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda


def _called_name(call: ast.Call) -> str | None:
    match call.func:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def _bound(function: _Function) -> set[str]:
    """The names ``function`` binds: its parameters and what it assigns."""
    args = function.args
    names = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    names |= {a.arg for a in (args.vararg, args.kwarg) if a is not None}
    body = [function.body] if isinstance(function, ast.Lambda) else function.body
    for statement in body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
    return names


def _methods(owner: ast.ClassDef | None) -> dict[str, _Function]:
    if owner is None:
        return {}
    return {f.name: f for f in owner.body if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef)}


def _thunks(
    arg: ast.expr, owner: ast.ClassDef | None, enclosing: list[_Function]
) -> list[_Function]:
    match arg:
        case ast.Lambda():
            return [arg]
        case ast.Attribute(value=ast.Name(id="self"), attr=name) if name in _methods(owner):
            return [_methods(owner)[name]]
        case ast.Name(id=name):
            for function in reversed(enclosing):
                for node in ast.walk(function):
                    if (
                        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                        and node.name == name
                    ):
                        return [node]
            return []
        case _:
            return []


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _reached_raw(
    thunk: _Function, owner: ast.ClassDef | None, parents: dict[ast.AST, ast.AST], seen: set[int]
) -> Iterator[ast.AST]:
    """Where ``thunk``, or a ``self`` method it calls, reaches a descriptor
    other than through ``OwnedFd``."""
    if id(thunk) in seen:
        return
    seen.add(id(thunk))
    methods = _methods(owner)
    for node in ast.walk(thunk):
        inner = _innermost(node, parents, thunk)
        match node:
            case ast.Attribute(attr=name) if _DESCRIPTOR.search(name) and not _owned_use(
                node, parents
            ):
                yield node
            case ast.Name(id=name, ctx=ast.Load()) if (
                _DESCRIPTOR.search(name)
                and name not in _bound(inner)
                and not _owned_use(node, parents)
            ):
                yield node
            case ast.Call(
                func=ast.Attribute(value=ast.Name(id="os"), attr=call), args=[first, *_]
            ) if call in _OS_TAKING_A_DESCRIPTOR and not (
                isinstance(first, ast.Name) and first.id in _bound(inner)
            ):
                yield node
            case ast.Call(func=ast.Attribute(value=ast.Name(id="self"), attr=name)) if (
                name in methods
            ):
                yield from _reached_raw(methods[name], owner, parents, seen)
            case _:
                pass


def _innermost(node: ast.AST, parents: dict[ast.AST, ast.AST], thunk: _Function) -> _Function:
    """The function ``node`` is in, within ``thunk``."""
    current = parents.get(node)
    while current is not None and current is not thunk:
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            return current
        current = parents.get(current)
    return thunk


def _owned_use(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """``node`` is the owner in ``node.use(...)``, ``node.using()`` or
    ``node.close_when_unused()``."""
    method = parents.get(node)
    return (
        isinstance(method, ast.Attribute)
        and method.attr in _OWNED
        and isinstance(parents.get(method), ast.Call)
    )


def _offenders(path: Path, root: Path) -> Iterator[str]:
    tree = _source.tree(path)
    parents = _parents(tree)

    def walk(
        node: ast.AST, owner: ast.ClassDef | None, enclosing: list[_Function]
    ) -> Iterator[str]:
        if isinstance(node, ast.ClassDef):
            owner = node
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            enclosing = [*enclosing, node]
        elif isinstance(node, ast.Call) and _called_name(node) in _HANDOFFS:
            for arg in [*node.args, *(k.value for k in node.keywords)]:
                for thunk in _thunks(arg, owner, enclosing):
                    for raw in _reached_raw(thunk, owner, parents, set()):
                        yield f"{path.relative_to(root)}:{getattr(raw, 'lineno', 0)}"
        for child in ast.iter_child_nodes(node):
            yield from walk(child, owner, enclosing)

    yield from walk(tree, None, [])


def offenders(root: Path) -> list[str]:
    return sorted({o for path in _source.files(root) for o in _offenders(path, root)})


def test_threads_reach_descriptors_only_through_owned_fd():
    assert offenders(_SOURCE) == [], (
        "hand the descriptor over as an OwnedFd and reach it with .use / .using"
    )


_CAUGHT = {
    "file.py": """
class File:
    def write(self, data):
        return run("write", self._fd, lambda: os.write(self._fd, data))
""",
    "release.py": """
def release(fd, _exit):
    return run("open", fd, lambda: os.close(fd))
""",
    "listener.py": """
def start(self, sock):
    return self.submit(lambda: self.server.serve(sockets=[sock]))
""",
    "writer.py": """
class Writer:
    def __init__(self):
        threading.Thread(target=self._run).start()

    def _run(self):
        self._send()

    def _send(self):
        self._sock.sendall(b"x")
""",
    "loop.py": """
class Udp:
    def close(self):
        call_soon(self._close_on_loop)

    def _close_on_loop(self):
        self._sock.close()
""",
}

_ALLOWED = """
class File:
    def write(self, data):
        return run("write", self._number, lambda: self._fd.use(lambda fd: os.write(fd, data)))

    def close(self):
        call_soon(self._fd.close_when_unused)

    def start(self):
        threading.Thread(target=self._run).start()

    def _run(self):
        with self._sock.using() as sock:
            sock.sendall(b"x")
"""


def test_the_guard_finds_each_way_of_reaching_a_raw_descriptor(tmp_path: Path):
    for name, source in _CAUGHT.items():
        (tmp_path / name).write_text(source)
    (tmp_path / "allowed.py").write_text(_ALLOWED)
    found = {offender.split(":")[0] for offender in offenders(tmp_path)}
    assert found == set(_CAUGHT)
