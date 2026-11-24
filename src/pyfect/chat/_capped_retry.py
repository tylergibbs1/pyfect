"""``chat_adapter.retry_safe`` with a ceiling on the platform's
``retry_after``, and the ``Retry-After`` header read as that wait. Shared by
the adapters with a ``max_retry_after`` option."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pyfect as fx
from pyfect._core import Effect
from pyfect.chat.chat_adapter import retry_safe
from pyfect.chat.chat_error import ChatError
from pyfect.duration import Duration, seconds

_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def parse_retry_after(value: str | None) -> Duration | None:
    """A ``Retry-After`` header in seconds, or ``None``."""
    if value is None:
        return None
    text = value.strip()
    if text and _DECIMAL.fullmatch(text) is None:
        return None
    number = float(text) if text else 0.0
    return seconds(number) if 0 <= number < float("inf") else None


@dataclass(frozen=True)
class _TooLong:
    error: ChatError


def retry_safe_within[A, R](
    effect: Effect[A, ChatError, R], max_retry_after: Duration | None
) -> Effect[A, ChatError, R]:
    """``retry_safe``, except that a failure asking to wait longer than
    ``max_retry_after`` fails at once, its ``retry_after`` kept for the
    caller. ``None`` waits out any ``retry_after``."""
    if max_retry_after is None:
        return retry_safe(effect)
    limit = max_retry_after

    def too_long(error: ChatError) -> bool:
        wait = error.retry_after
        return wait is not None and wait > limit

    # Hidden from retry_safe as a success, so it never sleeps on it.
    shielded: Effect[A | _TooLong, ChatError, R] = effect.catch_if(
        too_long, lambda error: fx.succeed(_TooLong(error))
    )

    def settled(result: A | _TooLong) -> Effect[A, ChatError]:
        return fx.fail(result.error) if isinstance(result, _TooLong) else fx.succeed(result)

    return retry_safe(shielded).flat_map(settled)
