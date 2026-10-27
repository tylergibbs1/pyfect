"""``Cache`` and ``ScopedCache``: effectful lookups shared by key.

A cache runs ``lookup(key)`` the first time a key is asked for and shares
the outcome, success or failure, with every later caller. Callers asking
while a lookup runs wait for that one lookup::

    users = yield from fx.Cache.make(fetch_user, capacity=1000, time_to_live=60)
    user = yield from users.get(user_id)

- ``capacity``: the most entries kept; the least recently used go first
  (``get``, ``get_option`` and ``get_success`` count as a use;
  ``has`` does not).
- ``time_to_live``: a duration, or a function of the lookup's ``Exit`` and
  the key, read from the ``Clock`` when the lookup ends. Zero keeps
  nothing in a ``Cache``; the default is forever. Expired entries are
  dropped when next read.
- ``ScopedCache``: each entry's lookup runs in a scope of its own, closed
  when the entry leaves the cache, and every entry's when the scope the
  cache was made in closes.

Keys compare with ``==`` and ``hash``: use frozen dataclasses or tuples
for structured keys.
"""

from pyfect.cache._cache import Cache
from pyfect.cache._expiry import RequireServicesAt, TimeToLive
from pyfect.cache._scoped_cache import ScopedCache

__all__ = ["Cache", "RequireServicesAt", "ScopedCache", "TimeToLive"]
