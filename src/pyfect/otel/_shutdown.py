"""Releasing an SDK provider when its layer is released."""

from __future__ import annotations

from typing import Protocol

from pyfect._core import Effect
from pyfect.duration import Duration, to_millis
from pyfect.effect import try_

DEFAULT_SHUTDOWN_TIMEOUT: Duration = "3 seconds"
"""How long a provider may take to flush when released."""


class Flushable(Protocol):
    def force_flush(self, timeout_millis: int = ..., /) -> bool: ...

    def shutdown(self) -> object: ...


def flush_and_shut_down(provider: Flushable, timeout: Duration) -> Effect[None]:
    """Flush ``provider`` (waiting at most ``timeout``), then shut it down
    even if the flush failed. Errors are ignored, as Effect ignores them."""
    flush = try_(lambda: provider.force_flush(int(to_millis(timeout))))
    shut_down = try_(provider.shutdown).ignore()
    return flush.ensuring(shut_down).ignore()
