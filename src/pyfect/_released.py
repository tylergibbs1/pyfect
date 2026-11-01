"""Use after release: a service kept past the scope that owns it.

A value made inside ``.pipe(provide(layer))`` can outlive the layer, which
is released once the effect it was provided to ends. Every resource pyfect
releases fails a later use with its own typed error carrying
``closed_message(owner)``, rather than hanging or raising a defect from a
thread pool or event loop that has stopped.

``Lifetime`` is that check for a resource that hands work to a thread or
loop of its own: ``submit`` gives a future failed with ``Released`` once
the lifetime is closed, also when the executor or loop stopped first.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future


def closed_message(owner: str) -> str:
    """Why ``owner`` can't be used: the scope that owns it closed."""
    return f"the {owner} is closed (used after the scope that owns it closed)"


class Released(RuntimeError):
    """``owner`` was used after the scope that owns it closed."""

    def __init__(self, owner: str) -> None:
        super().__init__(closed_message(owner))
        self.owner = owner


class Lifetime:
    """Whether a resource owning a thread or loop is still open."""

    __slots__ = ("_closed", "owner")

    def __init__(self, owner: str) -> None:
        self.owner = owner
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True

    def error(self) -> Released:
        return Released(self.owner)

    def submit[A](self, start: Callable[[], Future[A]]) -> Future[A]:
        """``start()``, or a future failed with ``Released`` once closed.
        A ``RuntimeError`` from ``start`` after closing (an executor shut
        down, a loop closed) is that same failure."""
        if not self._closed:
            try:
                return start()
            except RuntimeError:
                if not self._closed:
                    raise
        failed: Future[A] = Future()
        failed.set_exception(self.error())
        return failed


__all__ = ["Lifetime", "Released", "closed_message"]
