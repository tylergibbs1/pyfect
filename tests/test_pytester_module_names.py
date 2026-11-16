"""Modules a test writes with ``pytester`` never take a standard library module's name.

``test_vitest.py`` wrote a helper named ``resource``: on Python 3.13 the standard library's
``resource`` was already imported, so the inner tests imported that one and failed.
"""

import ast
import sys

import _source

TESTS = _source.TESTS
_WRITERS = {"makepyfile", "makeconftest", "makefile"}


def test_no_pytester_module_shadows_the_standard_library():
    shadowing = [
        f"{path.relative_to(TESTS)}:{node.lineno} {keyword.arg}"
        for path in _source.files(TESTS)
        for node in _source.walk(path)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _WRITERS
        for keyword in node.keywords
        if keyword.arg in sys.stdlib_module_names
    ]
    assert shadowing == []
