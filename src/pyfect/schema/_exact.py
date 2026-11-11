"""``Exact[A, RD, RE]``: a schema parameter that fixes ``A``.

``Codec`` is covariant in its Type, so in ``f(schema: Codec[A, ...], value: A)``
pyright widens ``A`` to accept any ``value`` (``Claims | dict[str, int]``).
Effect reads the value's type off the schema (``S["Type"]``); taking the
schema as ``Exact`` does the same here: its ``make`` takes and gives ``A``,
so ``A`` is the schema's Type exactly and the value is checked against it
(``research/typing/workflow_2_exact_schemas.py``).
``tests/test_schema_value_params.py`` fails on a signature that pairs a
``Codec[A, ...]`` with a parameter typed ``A``.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from pyfect.schema._schema import Codec


class _ExactBottom[A, RD, RE](Protocol):
    def make(self, input: A, /) -> A: ...

    def __codec__(self) -> Codec[object, object, RD, RE]: ...


class Exact[A, RD = Any, RE = Any](Protocol):
    """A schema of exactly ``A`` values, needing ``RD`` to decode and ``RE``
    to encode."""

    def __codec__(self) -> _ExactBottom[A, RD, RE]: ...


def as_codec[A, RD, RE](schema: Exact[A, RD, RE]) -> Codec[A, Any, RD, RE]:
    """The schema as a ``Codec`` (it is one: ``Exact`` only fixes ``A``)."""
    return cast("Codec[A, Any, RD, RE]", schema)
