"""Tests sharing a database name their tables through ``tests/_db_names.py``."""

import ast

import _source
from _db_names import fresh_name, owns_table

_TESTS = _source.TESTS


def test_no_two_names_repeat_whatever_their_kind_and_module() -> None:
    names = [fresh_name(kind) for kind in ("legacy", "legacy", "cluster")]
    assert len(set(names)) == len(names)


def test_a_name_owns_its_tables_and_not_those_of_a_longer_name() -> None:
    assert owns_table("legacy_7_1", "legacy_7_1_events")
    assert owns_table("legacy_7_1", "LEGACY_7_1_RUNNERS")
    assert not owns_table("legacy_7_1", "legacy_7_16_runners")
    assert not owns_table("legacy_7_1", "legacy_7_1")


def _calls(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Name) and n.func.id == name)
            or (isinstance(n.func, ast.Attribute) and n.func.attr == name)
        )
        for n in ast.walk(node)
    )


def test_no_test_counts_names_of_its_own() -> None:
    """A name built from the pid and a counter of the module's own repeats another module's:
    use ``fresh_name``."""
    offenders = [
        f"{path.relative_to(_TESTS)}:{node.lineno}"
        for path in _source.files(_TESTS)
        if path.name != "_db_names.py"
        for node in ast.walk(_source.tree(path))
        if isinstance(node, ast.JoinedStr) and _calls(node, "getpid") and _calls(node, "next")
    ]
    assert offenders == []
