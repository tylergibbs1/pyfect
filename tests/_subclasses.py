"""Subclass walks for tests that check every class of a kind.

``type.__subclasses__()`` also lists classes their module has replaced: CPython 3.14.4 keeps
each frozen ``slots=True`` dataclass's pre-slots class alive (its ``__setattr__`` closes over
it), so a raw walk saw every such class twice. ``tests/test_subclass_walks.py`` keeps raw walks
out of the tests.
"""

from __future__ import annotations

import sys


def subclasses[T](base: type[T], *, recursive: bool = True) -> set[type[T]]:
    """The classes under ``base`` (``recursive=False``: its direct subclasses), without
    those a module has replaced by a class of the same name."""
    found: set[type[T]] = set()
    todo = [base]
    while todo:
        for sub in todo.pop().__subclasses__():
            if sub not in found:
                found.add(sub)
                if recursive:
                    todo.append(sub)
    return {cls for cls in found if not _replaced(cls)}


def _replaced(cls: type) -> bool:
    current = getattr(sys.modules.get(cls.__module__), cls.__qualname__, cls)
    return (
        current is not cls
        and isinstance(current, type)
        and (current.__module__, current.__qualname__) == (cls.__module__, cls.__qualname__)
    )
