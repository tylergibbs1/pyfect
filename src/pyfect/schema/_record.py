"""``Record``: a mapping of keys of one schema to values of another."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pyfect.schema import ast
from pyfect.schema._schema import Bottom, Codec


@dataclass(frozen=True, slots=True, eq=False)
class RecordSchema[K, V, KI, VI, RD, RE](Bottom[dict[K, V], Mapping[KI, VI], RD, RE]):
    """A mapping of ``key`` values to ``value`` values."""

    key: Codec[K, KI, RD, RE]
    value: Codec[V, VI, RD, RE]


def Record[K, V, KI, VI, RD, RE](
    key: Codec[K, KI, RD, RE], value: Codec[V, VI, RD, RE], /
) -> RecordSchema[K, V, KI, VI, RD, RE]:
    """A mapping whose keys ``key`` accepts, with values of ``value``
    (Effect's ``Record``). A literal key (``S.Literal``, ``S.Literals``) is
    required; any other key schema takes the keys it accepts, its checks
    included, and the other keys are excess: dropped, or rejected under
    ``on_excess_property="error"``."""
    return RecordSchema(ast.record(key.__codec__().ast, value.__codec__().ast), key, value)
