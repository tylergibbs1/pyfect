"""The primitive schemas."""

from __future__ import annotations

from typing import Any as _Any
from typing import Never as _Never

from pyfect.schema import ast
from pyfect.schema._schema import Bottom

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
