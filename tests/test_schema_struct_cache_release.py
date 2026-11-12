"""A TypedDict made at run time is freed once the program drops it, recursive or not.

``S.Struct`` caches each TypedDict's derived AST in a table weakly keyed by the class.
A recursive TypedDict's AST refers back to itself through a ``Suspend``, which looked
the AST up by the class, so the entry reached its own key and the class (with its AST)
was never freed: one per class made per tenant or plugin. The ``Suspend`` now holds the
AST it waits for, not the class. Found auditing weak-keyed tables after the soak test
(tests/soak) found the same flaw in the HTTP client.
"""

from __future__ import annotations

import gc
import weakref
from typing import Any, TypedDict

from pyfect import schema as S


def _made_and_dropped(recursive: bool) -> weakref.ref[type]:
    """Make a TypedDict, derive its schema, decode with it, and drop both."""

    class Node(TypedDict):
        name: str
        children: list[Any]

    if recursive:
        Node.__annotations__["children"] = list[Node]
    schema = S.Struct(Node)
    decoded: Any = S.decode_unknown_sync(schema)({"name": "a", "children": []})
    assert decoded == {"name": "a", "children": []}
    return weakref.ref(Node)


def test_a_recursive_typed_dict_made_at_run_time_is_freed() -> None:
    ref = _made_and_dropped(recursive=True)
    gc.collect()
    assert ref() is None


def test_a_plain_typed_dict_made_at_run_time_is_freed() -> None:
    ref = _made_and_dropped(recursive=False)
    gc.collect()
    assert ref() is None
