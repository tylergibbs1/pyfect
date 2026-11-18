"""Completing an asyncio future from a callback, and waiting for one
without cancelling it.

A future handed to a callback (a fiber's exit observer, a
``call_soon_threadsafe``) can be cancelled before the callback runs, when
the task awaiting it is cancelled. ``set_result`` then raises
``InvalidStateError`` into whoever called the callback, which for an exit
observer stops the fiber's other observers. ``settle`` is the one way pyfect
completes such a future (``tests/test_future_callbacks.py``).

``await_uncancelled`` is the one way pyfect waits for a future that must
outlive a cancelled waiter (``tests/test_asyncio_shield_guard.py``). Some
``asyncio.shield`` releases (3.14.7 among them) report the future's later
failure to the loop's exception handler even when it is retrieved.
"""

from __future__ import annotations

import asyncio


def settle[A](future: asyncio.Future[A], value: A) -> None:
    """Set ``future``'s result, unless it is already done (cancelled)."""
    if not future.done():
        future.set_result(value)


def _retrieve[A](future: asyncio.Future[A]) -> None:
    """Mark the outcome of a future nobody waits for any more as seen."""
    if not future.cancelled():
        future.exception()


async def await_uncancelled[A](future: asyncio.Future[A]) -> A:
    """``future``'s result. Cancelling the waiting task raises here and
    leaves ``future`` running; its outcome is then marked seen when it ends."""
    try:
        await asyncio.wait((future,))
    except asyncio.CancelledError:
        future.add_done_callback(_retrieve)
        raise
    return future.result()
