"""A Connector 429's ``Retry-After`` is waited out before the retry, up to
``max_retry_after`` when the layer has one: Teams can ask for an hour, and a
post that waits that long holds up whatever queues behind it."""

from __future__ import annotations

from _teams_fake import CONVERSATION, Bot, Gen, Sent, teams_layer

import pyfect as fx
from pyfect import testing
from pyfect.chat import chat
from pyfect.chat.chat_error import RateLimited
from pyfect.chat.teams import teams_chat
from pyfect.duration import seconds

THREAD = teams_chat.thread(CONVERSATION)
ACTIVITIES = (
    "https://smba.trafficmanager.net/teams/v3/conversations/19%3Aconformance%40thread.tacv2"
    "/activities"
)


def rate_limited(bot: Bot, retry_after: str, times: int) -> None:
    """The first ``times`` posts are answered 429 with ``retry_after``."""
    answered = [0]

    def answer(_sent: Sent) -> tuple[int, object]:
        answered[0] += 1
        if answered[0] > times:
            return 200, {"id": "1"}
        return 429, {"error": {"code": "TooManyRequests"}}

    bot.answers[ACTIVITIES] = answer
    bot.headers[ACTIVITIES] = lambda _sent: (
        {"retry-after": retry_after} if answered[0] <= times else {}
    )


def posts(bot: Bot) -> int:
    return sum(1 for sent in bot.sent if sent.method == "POST" and sent.url.href == ACTIVITIES)


@testing.effect
def test_fails_at_once_with_the_wait_when_retry_after_passes_max_retry_after():
    bot = Bot()
    rate_limited(bot, "3600", times=1)

    @fx.gen
    def program() -> Gen[None]:
        service = yield from chat.Chat()
        error = yield from service.post(THREAD, markdown="alert").flip()
        assert isinstance(error.reason, RateLimited)
        assert error.retry_after == seconds(3600)
        assert posts(bot) == 1

    return program.pipe(fx.provide(teams_layer(bot, max_retry_after="1 minute")))


@testing.effect
def test_waits_out_a_retry_after_within_max_retry_after():
    bot = Bot()
    rate_limited(bot, "60", times=1)

    @fx.gen
    def program() -> Gen[None]:
        service = yield from chat.Chat()
        fiber = yield from service.post(THREAD, markdown="alert").fork()
        yield from testing.adjust("59 seconds")
        assert posts(bot) == 1
        yield from testing.adjust("1 second")
        posted = yield from fiber.join()
        assert posted.id == "1"
        assert posts(bot) == 2

    return program.pipe(fx.provide(teams_layer(bot, max_retry_after="1 minute")))


@testing.effect
def test_waits_out_any_retry_after_without_max_retry_after():
    bot = Bot()
    rate_limited(bot, "3600", times=1)

    @fx.gen
    def program() -> Gen[None]:
        service = yield from chat.Chat()
        fiber = yield from service.post(THREAD, markdown="alert").fork()
        yield from testing.adjust("1 hour")
        yield from fiber.join()
        assert posts(bot) == 2

    return program.pipe(fx.provide(teams_layer(bot)))
