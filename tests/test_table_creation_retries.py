"""Every ``CREATE`` of the SQL encrypted event log server storage retries.

Each instance creates the tables as it opens, at once with any other, and SQL Server and
PostgreSQL fail the loser of two creates that both found a table missing. The remote id and
session auth bindings tables were created once, so a storage opening alongside another failed
with "There is already an object named ..." (CI, 2026-11-20). A ``CREATE`` belongs in a
function that is retried: passed as ``gen(f).retry(...)`` where it is defined, or itself (or
a function around it) returning ``....retry(...)``.
"""

from __future__ import annotations

import ast
import re

import _source
from _source import SRC

_DIR = SRC / "eventlog" / "_sql_server_encrypted"
_CREATE = re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)\b", re.IGNORECASE)

type _Function = ast.FunctionDef | ast.AsyncFunctionDef


def _is_retry(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "retry"
    )


def _retried_gen_of(node: ast.AST) -> str | None:
    """``f`` of ``gen(f).retry(...)``."""
    if not _is_retry(node):
        return None
    assert isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    inner = node.func.value
    if (
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Name)
        and inner.func.id == "gen"
        and len(inner.args) == 1
        and isinstance(inner.args[0], ast.Name)
    ):
        return inner.args[0].id
    return None


def unretried_creates(module: ast.Module) -> list[int]:
    """The lines of ``CREATE`` statements in ``module`` that no retry covers."""
    enclosing: dict[ast.AST, _Function | None] = {}

    def visit(node: ast.AST, function: _Function | None) -> None:
        for child in ast.iter_child_nodes(node):
            enclosing[child] = function
            inner = child if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else None
            visit(child, inner or function)

    visit(module, None)

    def around(node: ast.AST) -> list[_Function | None]:
        """The functions ``node`` is in, innermost first, then the module (``None``)."""
        functions: list[_Function | None] = []
        function = enclosing[node]
        while function is not None:
            functions.append(function)
            function = enclosing[function]
        return [*functions, None]

    # (where ``f`` is defined, ``f``) of every ``gen(f).retry(...)``: the call may be in a
    # function nested where ``f`` is defined
    retried_in = {
        (scope, name)
        for node in enclosing
        if (name := _retried_gen_of(node)) is not None
        for scope in around(node)
    }

    def retried(function: _Function | None) -> bool:
        while function is not None:
            parent = enclosing[function]
            if (parent, function.name) in retried_in or any(
                isinstance(statement, ast.Return) and _is_retry(statement.value)
                for statement in function.body
            ):
                return True
            function = parent
        return False

    return sorted(
        node.lineno
        for node, function in enclosing.items()
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _CREATE.search(node.value)
        and not retried(function)
    )


def test_every_create_of_the_encrypted_storage_retries() -> None:
    files = _source.files(_DIR)
    unretried = [
        f"{path.relative_to(SRC).as_posix()}:{line}"
        for path in files
        for line in unretried_creates(_source.tree(path))
    ]
    assert not unretried, "CREATE statements with no retry:\n" + "\n".join(unretried)
    assert any(_CREATE.search(_source.text(path)) for path in files)


def test_the_guard_sees_a_create_with_no_retry() -> None:
    source = """
def created(sql):
    def body():
        yield from sql("CREATE TABLE IF NOT EXISTS t (a INT)")
    return gen(body)

def retried(sql):
    def body():
        yield from sql("CREATE TABLE IF NOT EXISTS t (a INT)")
    return gen(body).retry(times=3)

def inner_retried(sql):
    def legacy():
        yield from sql("CREATE INDEX IF NOT EXISTS i ON t (a)")
    def body():
        yield from gen(legacy).retry(times=3)
    return gen(body)

def same_name_elsewhere(sql):
    def legacy():
        yield from sql("CREATE TABLE t (a INT)")
    return gen(legacy)
"""
    assert unretried_creates(_source.parse(source)) == [4, 21]
