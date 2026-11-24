"""``chat_adapter.retry_safe``'s ``max_retry_after``: a platform's wait past it
is not waited out, and the error comes back with the wait on it."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect._core import Effect
from pyfect.chat.chat_adapter import retry_safe
from pyfect.chat.chat_error import ChatError, RateLimited
from pyfect.duration import Duration, hours, seconds

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]


def rate_limited(wait: Duration, attempts: list[int]) -> Effect[str, ChatError]:
    def run() -> Effect[str, ChatError]:
        attempts.append(1)
        if len(attempts) > 1:
            return fx.succeed("posted")
        return fx.fail(ChatError(platform="test", op="post", reason=RateLimited(retry_after=wait)))

    return fx.suspend(run)


@testing.effect
def test_a_wait_past_the_cap_fails_at_once_with_the_wait_on_the_error():
    @fx.gen
    def program() -> Gen[None]:
        attempts: list[int] = []
        error = yield from retry_safe(
            rate_limited(hours(1), attempts), max_retry_after=seconds(30)
        ).flip()
        assert attempts == [1]
        assert error.retry_after == hours(1)

    return program


@testing.effect
def test_a_wait_within_the_cap_is_waited_out():
    @fx.gen
    def program() -> Gen[None]:
        attempts: list[int] = []
        fiber = yield from retry_safe(
            rate_limited(seconds(30), attempts), max_retry_after=seconds(30)
        ).fork()
        yield from testing.adjust("30 seconds")
        assert (yield from fiber.join()) == "posted"
        assert len(attempts) == 2

    return program


@testing.effect
def test_without_a_cap_any_wait_is_waited_out():
    @fx.gen
    def program() -> Gen[None]:
        attempts: list[int] = []
        fiber = yield from retry_safe(rate_limited(hours(1), attempts)).fork()
        yield from testing.adjust("1 hour")
        assert (yield from fiber.join()) == "posted"

    return program
