"""``Tree(node)`` (Effect's ``Tree``): a node value, a tuple of trees or a
string-keyed dict of trees::

    S.Tree(S.Number).decode_unknown_sync({"a": [1, {"b": 2}]})
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pyfect.schema._arrays import Array
from pyfect.schema._literals import Union
from pyfect.schema._primitives import String
from pyfect.schema._record import Record
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema._struct import suspend

type TreeValue[N] = N | Sequence[TreeValue[N]] | Mapping[str, TreeValue[N]]
"""A node, a sequence of trees or a string-keyed mapping of trees (decoded
as a tuple and a dict)."""


def Tree[T, E, RD, RE](node: Codec[T, E, RD, RE], /) -> Bottom[TreeValue[T], TreeValue[E], RD, RE]:
    """The recursive schema of trees of ``node``'s values."""
    tree: Bottom[TreeValue[T], TreeValue[E], RD, RE] = suspend(lambda: schema)
    schema = Union(node, Array(tree), Record(String, tree))
    return schema
