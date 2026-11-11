"""Constructors that take their items as arguments or, as Effect v4 does, as
one array (``Schema.Literals([...])``, ``Schema.Union([...])``,
``Config.Literals([...])``)."""

from collections.abc import Sequence
from typing import Any, cast


def one_or_many(args: tuple[Any, ...]) -> tuple[Any, ...]:
    """``args``, or the items of ``args``' only item when it is a ``list`` or
    ``tuple``."""
    if len(args) == 1 and isinstance(args[0], (list, tuple)):
        return tuple(cast("Sequence[Any]", args[0]))
    return args
