"""Whether a hydrated value replaces a node's current one (Effect's
``internal/hydration``)."""

from __future__ import annotations

from pyfect.reactivity.async_result import Initial, Success, is_async_result


def should_hydrate(current: object, incoming: object) -> bool:
    """An ``Initial`` replaces only an ``Initial``, and a success only an
    older success; a failure has no timestamp, so it always replaces."""
    if not is_async_result(current) or not is_async_result(incoming):
        return True
    if isinstance(incoming, Initial):
        return isinstance(current, Initial)
    if isinstance(current, Success) and isinstance(incoming, Success):
        return incoming.timestamp >= current.timestamp
    return True
