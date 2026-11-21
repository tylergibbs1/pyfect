"""Every thread's frames are read through ``pyfect._frames.current_frames()``.

CPython 3.14 before 3.14.8 has ``sys._current_frames()`` make frame objects for the threads of
every interpreter, from the caller's allocator, and a subinterpreter frees them into its own heap
(python/cpython#158364): CI's 3.14.4 workers died in ``test_interpreter_pool.py`` while the
stall watchdog sampled stacks. The helper reads nothing while a pool's subinterpreter runs code,
so this guard fails any other read of ``sys._current_frames``."""

import ast

import _source

_ROOTS = ("src", "tests", "benchmarks", "examples", "scripts", "website")
_HELPER = _source.SRC / "_frames.py"


def _reads_current_frames(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr == "_current_frames"
    if isinstance(node, ast.ImportFrom) and node.module == "sys":
        return any(alias.name == "_current_frames" for alias in node.names)
    return False


def _offenders() -> list[str]:
    found: list[str] = []
    for root in _ROOTS:
        for path in _source.files(_source.ROOT / root):
            if path == _HELPER or not _source.mentions(path, "_current_frames"):
                continue
            found += [
                f"{path.relative_to(_source.ROOT)}:{node.lineno}"
                for node in _source.walk(path)
                if isinstance(node, (ast.Attribute, ast.ImportFrom)) and _reads_current_frames(node)
            ]
    return found


def test_only_the_frames_helper_reads_current_frames():
    assert _offenders() == []


def test_the_guard_sees_each_way_to_read_current_frames():
    def offends(source: str) -> bool:
        return any(_reads_current_frames(node) for node in ast.walk(_source.parse(source)))

    assert offends("sys._current_frames()")
    assert offends("frames = sys._current_frames")
    assert offends("from sys import _current_frames")
    assert not offends("current_frames()")
    assert not offends("sys._getframe()")
