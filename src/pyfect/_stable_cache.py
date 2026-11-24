"""Lazily filled caches that hand every caller of a key the same value, also when threads fill
them at once without the GIL. A value may be made more than once, but only the first one
stored is ever returned (``dict.setdefault`` is atomic). Use them wherever the identity of a
cached value matters (a tag class, a ``ZoneInfo``); ``tests/test_stable_cache_guard.py`` keeps
module-level dicts from being filled any other way."""

import functools
from collections.abc import Callable


class StableCache[K, V]:
    """A map from keys to values made on first use, the same value for every caller."""

    __slots__ = ("_values",)

    def __init__(self) -> None:
        self._values: dict[K, V] = {}

    def get(self, key: K, make: Callable[[], V]) -> V:
        """The value of ``key``, made by ``make`` unless one is stored."""
        try:
            return self._values[key]
        except KeyError:
            return self._values.setdefault(key, make())


def stable_cache[*Ts, V](make: Callable[[*Ts], V]) -> Callable[[*Ts], V]:
    """``make`` called once per arguments as far as its callers can tell: like
    ``functools.cache``, but every caller gets the same result, also when threads race."""
    values: dict[tuple[*Ts], V] = {}

    @functools.wraps(make)
    def cached(*args: *Ts) -> V:
        try:
            return values[args]
        except KeyError:
            return values.setdefault(args, make(*args))

    return cached
