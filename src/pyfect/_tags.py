"""``Tags[T]``: the classes a ``catch_tag`` or ``tap_error_tag`` matches.

One class, or a tuple of any number of them (Effect's ``catchTag`` takes
any number of tags). ``T`` is solved as the union of the classes::

    eff.pipe(fx.catch_tag((A, B, C, D), lambda e: ...))  # e: A | B | C | D

Every combinator taking classes to match uses this alias, so none caps
how many it takes (``tests/test_tag_tuples.py``).
"""

type Tags[T] = type[T] | tuple[type[T], ...]

__all__ = ["Tags"]
