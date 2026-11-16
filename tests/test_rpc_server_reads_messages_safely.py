"""The RPC server reads a client's encoded message only with ``.get`` or
through a decoder (``decode_control``): a key the client left out is then a
protocol error for that client, never a ``KeyError`` on the server."""

import ast
from pathlib import Path

import _source

import pyfect.rpc.server

SERVER = Path(pyfect.rpc.server.__file__).parent


def _indexes_a_message(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.ctx, ast.Load)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
        and isinstance(node.value, ast.Name)
        and node.value.id in {"message", "msg", "decoded", "encoded"}
    )


def _string_subscripts(path: Path) -> list[str]:
    return [
        f"{path.name}:{getattr(node, 'lineno', 0)} {ast.unparse(node)}"
        for node in _source.walk(path)
        if _indexes_a_message(node)
    ]


def test_no_server_module_indexes_a_client_message() -> None:
    found = [
        hit for path in _source.files(SERVER, recursive=False) for hit in _string_subscripts(path)
    ]
    assert found == []
