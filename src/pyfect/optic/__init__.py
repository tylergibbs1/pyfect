"""Optics: read and update a part of a value without changing the value
(Effect's ``Optic``)::

    from pyfect import optic

    likes = optic.Id[State]().key("posts").for_each(lambda post: post.key("likes"))
    likes.modify_all(lambda n: n + 1)(state)  # a new state; ``state`` is unchanged

An ``Iso`` converts both ways, a ``Lens`` always finds its focus, a
``Prism`` may not find it but builds a whole from it, an ``Optional`` may
fail both ways. Start a chain with ``Id[T]()`` and add ``key``,
``optional_key``, ``at``, ``tag``, ``check``, ``refine``, ``pick``,
``omit``, ``not_none`` and ``for_each``; ``compose`` joins two optics.
Failures are schema issues (``pyfect.schema.issue``). Optics copy dicts,
lists, tuples and values ``copy.replace`` supports (dataclasses, schema
classes); anything else raises ``TypeError`` when written.
"""

from pyfect.optic._builtins import entries, failure, from_checks, none, some, success
from pyfect.optic._optic import (
    Id,
    Iso,
    Lens,
    Optional,
    Prism,
    Traversal,
    make_iso,
    make_lens,
    make_optional,
    make_prism,
)

__all__ = [
    "Id",
    "Iso",
    "Lens",
    "Optional",
    "Prism",
    "Traversal",
    "entries",
    "failure",
    "from_checks",
    "make_iso",
    "make_lens",
    "make_optional",
    "make_prism",
    "none",
    "some",
    "success",
]
