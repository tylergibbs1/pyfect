"""JavaScript ``Set`` iteration over an insertion-ordered ``dict``.

Effect iterates live ``Set``s of listeners and handlers: one removed by an
earlier callback is skipped, and one added meanwhile is visited too.
Iterating a ``list`` snapshot gets both wrong, so every such loop in
``pyfect.reactivity`` goes through ``live_keys``.
"""

from collections.abc import Iterator


def live_keys[K](items: dict[K, None]) -> Iterator[K]:
    """The keys of ``items`` in order, each once, as ``items`` changes:
    a key removed before it is reached is skipped, one added is reached."""
    seen: dict[K, None] = {}
    while pending := [key for key in items if key not in seen]:
        for key in pending:
            if key in items:
                seen[key] = None
                yield key
