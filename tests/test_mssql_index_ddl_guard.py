"""The encrypted event log storage creates its tables whenever a server opens a
store, so several servers run that DDL at once. On SQL Server a table's
indexes are part of its ``CREATE TABLE`` (``tables.create_table``): a
separate ``CREATE INDEX`` checked against ``sys.indexes`` deadlocks with
another server's check, and SQL Server breaks that only after up to 5
seconds."""

from __future__ import annotations

import ast
from pathlib import Path

EVENTLOG = Path(__file__).resolve().parent.parent / "src" / "pyfect" / "eventlog"
MODULES = [*sorted((EVENTLOG / "_sql_server_encrypted").glob("*.py"))]
MODULES.append(EVENTLOG / "sql_event_log_server_encrypted.py")


def _separate_index_ddl(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), str(path))
    return [
        f"{path.name}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        if "sys.indexes" in node.value
        or ("CREATE INDEX" in node.value and "CREATE INDEX IF NOT EXISTS" not in node.value)
    ]


def test_sql_server_indexes_are_created_with_their_table() -> None:
    assert [hit for path in MODULES for hit in _separate_index_ddl(path)] == []
