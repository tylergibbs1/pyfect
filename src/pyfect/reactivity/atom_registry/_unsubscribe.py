"""The unsubscribe function of a listener that ends its own subscription."""

from __future__ import annotations

from collections.abc import Callable
from typing import final


@final
class Unsubscribe:
    """Ends the subscription ``set`` gives it, once, and then drops it: the
    listener holding this does not keep its own subscription (and what it
    sees) alive once it has ended."""

    __slots__ = ("_cancel",)

    def __init__(self) -> None:
        self._cancel: Callable[[], None] | None = None

    def set(self, cancel: Callable[[], None]) -> None:
        self._cancel = cancel

    def __call__(self) -> None:
        cancel, self._cancel = self._cancel, None
        if cancel is not None:
            cancel()
