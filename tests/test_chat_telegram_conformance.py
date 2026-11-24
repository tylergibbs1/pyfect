"""Port of Effect's ``packages/chat/telegram/test/conformance.test.ts``: the
conformance rules against the adapter with every ``unverified`` capability
on, over a fake Bot API that keeps what was sent. Clicks and commands are
built from what was sent and go through ``TelegramChatService.receive``."""

from __future__ import annotations

import pytest
from _telegram_fake import THREAD, Clicks, FakeApi, telegram_layer, user_posts

import pyfect as fx
from pyfect import testing
from pyfect.chat import chat_test
from pyfect.chat.telegram import telegram_chat


def rules(clicks: Clicks | None) -> dict[str, chat_test.Rule]:
    return chat_test.conformance(
        platform="telegram",
        thread=THREAD,
        user_posts=user_posts,
        parse_mention=telegram_chat.parse_mention,
        interactions=chat_test.Interactions(
            click=lambda _m, _i, _o: fx.void,
            submit=lambda _v: fx.void,
            command=lambda _t, _i, _x: fx.void,
        )
        if clicks is None
        else clicks.interactions,
    )


NAMES = list(rules(None))


@pytest.mark.parametrize("name", NAMES)
@testing.effect
def test_conformance_over_a_fake_bot_api(name: str):
    """conformance over a fake Bot API / {name}"""
    api = FakeApi()
    clicks = Clicks(api)
    return clicks.bind.flat_map(lambda _: rules(clicks)[name]).pipe(fx.provide(telegram_layer(api)))
