"""The psycopg connection behind a PostgreSQL session is reached only
through ``Session._using`` (``src/pyfect/sql/pg/_session.py``), apart from
a few loop-only helpers.

Each connection is touched only on the SQL loop thread, and ``close``
shuts the socket down and waits for the statements in flight before it
closes the connection (``tests/oracle/test_pg_close_while_reading.py``).
That holds only if nothing reaches the connection except through
``_using``. This guard enforces it: no other module in ``sql/pg`` touches
a connection attribute, and inside ``Session`` only the methods in
``_ALLOWED`` use ``self._conn``, so what fibers read on other threads is
a snapshot taken on the loop.
"""

import ast
from pathlib import Path

_PG = Path(__file__).resolve().parents[1] / "src" / "pyfect" / "sql" / "pg"
_SESSION = _PG / "_session.py"

_CONNECTION_ATTRIBUTES = frozenset({"conn", "_conn", "pgconn"})
"""Attribute names that reach a psycopg connection or its libpq handle."""

_ALLOWED = frozenset(
    {
        "__init__",
        "_observe",
        "_using",
        "_statement_active",
        "_send_cancel",
        "close",
        "_shut_down_socket",
    }
)
"""The ``Session`` methods that may use ``self._conn``: they run on the
loop, and none waits on the socket outside ``_using`` except ``close``."""


def _session_class(tree: ast.Module) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Session":
            return node
    raise AssertionError("Session not found")


def _self_conn_uses(function: ast.AST) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute)
        and node.attr == "_conn"
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ]


def test_only_the_session_module_reaches_a_psycopg_connection():
    found: list[str] = []
    for path in sorted(_PG.glob("*.py")):
        if path == _SESSION:
            continue
        found.extend(
            f"{path.name}:{node.lineno} .{node.attr}"
            for node in ast.walk(ast.parse(path.read_text(), str(path)))
            if isinstance(node, ast.Attribute) and node.attr in _CONNECTION_ATTRIBUTES
        )
    assert found == []


def test_the_session_reaches_its_connection_only_through_its_helpers():
    session = _session_class(ast.parse(_SESSION.read_text(), str(_SESSION)))
    found: list[str] = []
    for node in session.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name not in _ALLOWED:
                found += [f"{node.name}:{line}" for line in _self_conn_uses(node)]
        else:
            found += [f"class body:{line}" for line in _self_conn_uses(node)]
    assert found == []
    # A second attribute holding the connection would bypass ``_using``.
    assert not [
        node.lineno
        for node in ast.walk(session)
        if isinstance(node, ast.Attribute)
        and node.attr in {"conn", "pgconn"}
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ]


def test_the_guard_sees_a_direct_use():
    source = "class Session:\n    async def query(self):\n        await self._conn.execute('')\n"
    session = _session_class(ast.parse(source))
    query = session.body[0]
    assert _self_conn_uses(query) == [3]
