"""Server threads in tests accept connections through ``tests/_threaded_server.py``.

A test server that accepts on a thread of its own and closes its sockets from the test's
thread closes a socket a thread still owns: the descriptor goes to the next socket opened,
and the thread still blocked on it reads from and writes to that socket. A TLS echo server
did this and wrote a TLS alert into a later test's connection. ``serving`` shuts
connections down, joins their threads and only then closes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import _source

TESTS = Path(__file__).resolve().parent
_HELPER = TESTS / "_threaded_server.py"


def _thread_targets(tree: ast.AST) -> set[str]:
    """The names given as ``target=`` to any call (``threading.Thread`` or an alias of it)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg != "target":
                    continue
                if isinstance(keyword.value, ast.Name):
                    names.add(keyword.value.id)
                elif isinstance(keyword.value, ast.Attribute):
                    names.add(keyword.value.attr)
    return names


def _accepts(node: ast.AST) -> bool:
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "accept"
        and not call.args
        for call in ast.walk(node)
    )


def accepting_server_threads(tree: ast.AST) -> list[int]:
    """The lines of the functions run as threads that accept connections themselves, and of
    loops that accept connection after connection (a server, whatever thread runs it)."""
    targets = _thread_targets(tree)
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.FunctionDef) and node.name in targets and _accepts(node))
        or (isinstance(node, ast.While) and _accepts(node))
    )


def test_server_threads_use_the_helper():
    offenders = [
        f"{path.relative_to(TESTS)}:{line}"
        for path in _source.files(TESTS)
        if path != _HELPER and _source.mentions(path, "accept")
        for line in accepting_server_threads(_source.tree(path))
    ]
    assert offenders == [], "accept connections with _threaded_server.serving"


def test_the_guard_finds_a_thread_that_accepts():
    source = """
import socket, threading

def server():
    listener = socket.create_server(("127.0.0.1", 0))

    def accept():
        while True:
            conn, _ = listener.accept()

    threading.Thread(target=accept, daemon=True).start()

class Server:
    def __init__(self):
        self._thread = threading.Thread
        self._thread(target=self._serve).start()

    def _serve(self):
        self._socket.accept()
"""
    assert accepting_server_threads(_source.parse(source)) == [7, 8, 18]


def test_the_guard_finds_an_accept_loop_run_by_any_thread():
    source = """
def serve(listener):
    while True:
        conn, _ = listener.accept()

for target in (serve,):
    start(target)
"""
    assert accepting_server_threads(_source.parse(source)) == [3]


def test_the_guard_leaves_accepts_on_the_tests_own_thread():
    source = """
import socket

def test_accepts():
    with socket.create_server(("127.0.0.1", 0)) as listener:
        conn, _ = listener.accept()
"""
    assert accepting_server_threads(_source.parse(source)) == []
