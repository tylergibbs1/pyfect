"""The primitive schemas."""

from __future__ import annotations

from typing import Any as _Any
from typing import Never as _Never

from pyfect.schema import ast
from pyfect.schema._checks_number import (
    int_value,
    is_between,
    is_finite,
    is_greater_than_or_equal_to,
)
from pyfect.schema._checks_size import is_between_length, is_non_empty
from pyfect.schema._checks_string import is_trimmed
from pyfect.schema._schema import Bottom
from pyfect.schema.ast import append_checks

Never: Bottom[_Never] = Bottom(ast.never)
"""Accepts nothing."""
Any: Bottom[_Any] = Bottom(ast.any_)
"""Accepts anything, typed ``Any``."""
Unknown: Bottom[object] = Bottom(ast.unknown)
"""Accepts anything, typed ``object``."""
Null: Bottom[None] = Bottom(ast.null)
"""``None``."""
String: Bottom[str] = Bottom(ast.string)
Number: Bottom[float] = Bottom(ast.number)
"""An ``int`` or ``float`` (not a ``bool``): JavaScript's ``number``."""
Boolean: Bottom[bool] = Bottom(ast.boolean)
BigInt: Bottom[int] = Bottom(ast.big_int)
"""An ``int`` (not a ``bool``): Effect's ``bigint``, which Python's ``int`` is."""

Finite: Bottom[float] = Number.check(is_finite())
"""A number that is not ``NaN`` nor an infinity."""
Int: Bottom[int] = Bottom(append_checks(ast.whole_number, (int_value(),)))
"""An ``int`` (not a ``bool``): Effect's ``Int``, with its messages
(``Expected number``, then ``Expected an integer``). ``1.0`` is taken, as ``1``."""
Natural: Bottom[int] = Int.check(is_greater_than_or_equal_to(0))
"""An ``int`` from ``0``."""
Port: Bottom[int] = Int.check(is_between(minimum=0, maximum=65535, expected="a port number"))
"""An ``int`` from ``0`` to ``65535``."""
NonEmptyString: Bottom[str] = String.check(is_non_empty())
Char: Bottom[str] = String.check(is_between_length(1, 1))
"""A string of one character."""
Trimmed: Bottom[str] = String.check(is_trimmed())
"""A string with no leading or trailing whitespace."""
