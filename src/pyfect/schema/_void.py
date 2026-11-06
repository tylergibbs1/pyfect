"""Effect's ``Undefined``, ``Void`` and ``ObjectKeyword``."""

from __future__ import annotations

from types import NoneType
from typing import TypeIs

from pyfect.exit import Exit, Success
from pyfect.schema import ast
from pyfect.schema._declare import Parse, declare
from pyfect.schema._options import ParseOptions
from pyfect.schema._schema import Bottom
from pyfect.schema._undefined import Undefined, to_null_json
from pyfect.schema.issue import Issue


def _void_run(_: tuple[ast.AST, ...]) -> Parse[None]:
    def parse(_input: object, _node: ast.Declaration, _options: ParseOptions) -> Exit[None, Issue]:
        return Success(None)

    return parse


Void: Bottom[None, object] = Bottom(
    ast.Declaration(
        (),
        _void_run,
        annotations={"expected": "void", "to_codec_json": to_null_json},
    )
)
"""Takes anything and gives ``None``, in both directions, as ``void`` ignores a
value; JSON writes it as ``null``."""


def _is_object(value: object) -> TypeIs[object]:
    return not isinstance(value, str | bytes | int | float | NoneType)


def _object_strategy(_: tuple[object, ...]) -> object:
    from pyfect.schema._strategy import st

    return st.dictionaries(st.text(), st.integers())


ObjectKeyword: Bottom[object] = declare(
    _is_object, expected="object | array | function", to_arbitrary=_object_strategy
)
"""Anything but a primitive."""

__all__ = ["ObjectKeyword", "Undefined", "Void"]
