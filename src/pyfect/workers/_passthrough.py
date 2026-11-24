"""A ``to_codec_json`` link writing a value as itself: a worker message carries
the object, which its platform copies, moves or shares (Effect's internal
``passthroughLink``)."""

from __future__ import annotations

from pyfect.schema import ast
from pyfect.schema import transformation as T

_PASSTHROUGH: T.Transformation[object, object] = T.passthrough()
_LINK = ast.Link(ast.any_, _PASSTHROUGH)


def passthrough_link(_: tuple[ast.AST, ...]) -> ast.Link:
    return _LINK
