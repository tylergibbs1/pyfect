"""Generated decoders spell a literal as source only for an exact ``bool``, ``int``,
``str`` or ``float``; any other value (a subclass included) is a bound constant.

A ``str`` subclass's ``__repr__`` used to be pasted into the source the JIT runs, so a
literal whose ``repr`` was not its value made the decoder run that text (and an
``IntEnum`` literal gave source that did not compile).
"""

import enum
from typing import LiteralString, cast

from pyfect import schema as S
from pyfect.schema.compiler import _codegen as codegen


class _Shouty(str):
    __slots__ = ()

    def __repr__(self) -> str:
        return "MARKER()"


class _Level(enum.IntEnum):
    LOW = 1


def test_a_literal_subclass_is_a_constant_not_source():
    source = codegen.generate(S.Array(S.Literal(cast("LiteralString", _Shouty("a")))).ast, "is")
    assert source is not None
    assert "MARKER" not in source


def test_an_int_enum_literal_compiles():
    source = codegen.generate(S.Array(S.Literal(_Level.LOW)).ast, "is")
    assert source is not None
    body = "".join(f"    {line}\n" for line in source.splitlines())
    compile(f"def factory(ast, R, resolve):\n{body}", "<generated>", "exec")
