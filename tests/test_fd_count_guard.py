"""Tests count only the descriptors their code opened (``_connection_release.connected_to``).

Counting every descriptor of the process (``/dev/fd``, ``/proc/self/fd``) picks up
sockets and pipes other tests' threads close meanwhile: under pytest-xdist a
connection-release test counted ``-1`` open sockets (CI run 43743608270). The soak
runs measure the whole process on purpose, in a process of their own."""

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent
_PROCESS_FDS = frozenset({"/dev/fd", "/proc/self/fd"})
_ALLOWED = frozenset({Path("_connection_release.py"), Path("test_fd_count_guard.py")})


def _lists_process_fds(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value in _PROCESS_FDS


def test_tests_count_only_their_own_descriptors():
    offenders = [
        f"{relative}:{getattr(node, 'lineno', 0)}"
        for path in sorted(TESTS.rglob("*.py"))
        if (relative := path.relative_to(TESTS)) not in _ALLOWED and relative.parts[0] != "soak"
        for node in ast.walk(ast.parse(path.read_text(), str(path)))
        if _lists_process_fds(node)
    ]
    assert offenders == [], "count the sockets connected to your server, as connected_to does"
