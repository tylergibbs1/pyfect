"""``Record``: a mapping of keys of one schema to values of another."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

from pyfect.schema import ast
from pyfect.schema._schema import Bottom, Codec

# Explicit covariant parameters: a frozen dataclass's fields would make
# inferred ones invariant (``tests/test_schema_variance.py``).
K_ = TypeVar("K_")
V_ = TypeVar("V_")
KI_ = TypeVar("KI_")
VI_co = TypeVar("VI_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)


@dataclass(frozen=True, slots=True, eq=False)
class RecordSchema(
    Bottom[dict[K_, V_], Mapping[KI_, VI_co], RD_co, RE_co],
    Generic[K_, V_, KI_, VI_co, RD_co, RE_co],
):
    """A mapping of ``key`` values to ``value`` values."""

    key: Codec[K_, KI_, RD_co, RE_co]
    value: Codec[V_, VI_co, RD_co, RE_co]


def Record[K, V, KI, VI, RD, RE](
    key: Codec[K, KI, RD, RE], value: Codec[V, VI, RD, RE], /
) -> RecordSchema[K, V, KI, VI, RD, RE]:
    """A mapping whose keys ``key`` accepts, with values of ``value``
    (Effect's ``Record``). A literal key (``S.Literal``, ``S.Literals``) is
    required; any other key schema takes the keys it accepts, its checks
    included, and the other keys are excess: dropped, or rejected under
    ``on_excess_property="error"``."""
    return RecordSchema(ast.record(key.__codec__().ast, value.__codec__().ast), key, value)
