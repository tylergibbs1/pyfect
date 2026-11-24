"""A Slack 429's ``Retry-After`` is waited out before the retry, up to
``max_retry_after`` when the layer has one: Slack can ask for an hour, and a
post that waits that long holds up whatever queues behind it."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from _slack_fake import CHANNEL, TEAM, Fake, Status

import pyfect as fx
from pyfect import layer, testing
from pyfect._core import Effect
from pyfect.chat import chat
from pyfect.chat.chat_error import RateLimited
from pyfect.chat.slack import slack_chat
from pyfect.duration import seconds
from pyfect.redacted import make as redacted

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

THREAD = slack_chat.thread(team=TEAM, channel=CHANNEL)
POSTED = {"ok": True, "channel": CHANNEL, "ts": "1794600000.000100"}


def rate_limited(retry_after: str) -> Fake:
    """The first post is answered 429 with ``retry_after``, the next ``ok``."""
    return Fake({"chat.postMessage": [Status(429, headers={"retry-after": retry_after}), POSTED]})


def app(fake: Fake, max_retry_after: str | None = None) -> layer.Layer[Any]:
    return (
        slack_chat.layer(
            bot_token=redacted("xoxb-test"), team_id=TEAM, max_retry_after=max_retry_after
        )
        .pipe(layer.provide_merge(chat.layer))
        .pipe(layer.provide(fake.layer))
    )


def post() -> Effect[Any, Any, chat.Chat]:
    return chat.Chat().flat_map(lambda service: service.post(THREAD, markdown="alert"))


@testing.effect
def test_fails_at_once_with_the_wait_when_retry_after_passes_max_retry_after():
    fake = rate_limited("3600")

    @fx.gen
    def program() -> Gen[None]:
        error = yield from post().flip()
        assert isinstance(error.reason, RateLimited)
        assert error.retry_after == seconds(3600)
        assert len(fake.called("chat.postMessage")) == 1

    return program.pipe(fx.provide(app(fake, max_retry_after="1 minute")))


@testing.effect
def test_waits_out_a_retry_after_within_max_retry_after():
    fake = rate_limited("30")

    @fx.gen
    def program() -> Gen[None]:
        fiber = yield from post().fork()
        yield from testing.adjust("29 seconds")
        assert len(fake.called("chat.postMessage")) == 1
        yield from testing.adjust("1 second")
        posted = yield from fiber.join()
        assert posted.id == POSTED["ts"]
        assert len(fake.called("chat.postMessage")) == 2

    return program.pipe(fx.provide(app(fake, max_retry_after="1 minute")))


@testing.effect
def test_waits_out_any_retry_after_without_max_retry_after():
    fake = rate_limited("3600")

    @fx.gen
    def program() -> Gen[None]:
        fiber = yield from post().fork()
        yield from testing.adjust("1 hour")
        yield from fiber.join()
        assert len(fake.called("chat.postMessage")) == 2

    return program.pipe(fx.provide(app(fake)))


@testing.effect
def test_an_edit_past_max_retry_after_fails_at_once():
    """An edit retries outside the Web API client, with the same cap."""
    fake = Fake(
        {"chat.postMessage": POSTED, "chat.update": Status(429, headers={"retry-after": "3600"})}
    )

    @fx.gen
    def program() -> Gen[None]:
        service = yield from chat.Chat()
        posted = yield from service.post(THREAD, markdown="alert")
        # Edits to one message are paced 3 seconds apart.
        fiber = yield from service.edit(THREAD, posted.id, markdown="fixed").flip().fork()
        yield from testing.adjust("3 seconds")
        error = yield from fiber.join()
        assert error.retry_after == seconds(3600)
        assert len(fake.called("chat.update")) == 1

    return program.pipe(fx.provide(app(fake, max_retry_after="1 minute")))
