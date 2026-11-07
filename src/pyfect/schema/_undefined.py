"""Effect's ``Schema.Undefined`` for schemas whose wire form must match Effect's
(``Schema.optional``, ``RpcMessage.EncodedSchema``'s optional fields). Python has
one absent value, so its values are ``None``; ``S.Null`` stays a different
layout, and JSON writes both as ``null``, as Effect's does."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeIs, cast

from pyfect.schema import ast
from pyfect.schema._codec_links import link
from pyfect.schema._declare import declare
from pyfect.schema._schema import Bottom

UNDEFINED_ID = "pyfect/schema/Undefined"


def _is_none(value: object) -> TypeIs[None]:
    return value is None


def _none_strategy(_: tuple[object, ...]) -> object:
    from pyfect.schema._strategy import st

    return st.none()


def _nothing(_: object) -> None:
    return None


def to_null_json(_: tuple[ast.AST, ...]) -> ast.Link:
    """JSON writes ``undefined`` and ``void`` as ``null``, and reads only that."""
    return link(ast.null, decode=_nothing, encode=_nothing)


def stays_absent_in_a_string_tree(_: tuple[ast.AST, ...]) -> None:
    """A string tree holds ``undefined`` itself, as ``None``; ``S.Null`` is the text ``null``."""


Undefined: Bottom[None] = declare(
    _is_none,
    expected="undefined",
    to_codec_json=to_null_json,
    to_codec_string_tree=stays_absent_in_a_string_tree,
    representation={"id": UNDEFINED_ID, "payload": None},
    to_arbitrary=_none_strategy,
)


def is_undefined(node: ast.AST) -> bool:
    representation = (node.annotations or {}).get("representation")
    if not isinstance(representation, Mapping):
        return False
    return cast("Mapping[str, object]", representation).get("id") == UNDEFINED_ID
