"""Port of Effect's ``packages/chat/teams/test/conformance.test.ts``: the
conformance suite against the default layer, over a stubbed Connector that
answers every write. Capabilities behind ``unverified`` are off, so their
rules check that the descriptor leaves them out and the ops refuse."""

from __future__ import annotations

import json

import pytest
from _teams_fake import CONVERSATION, INTERACTION_KEY, Bot, Gen, teams_layer, user_posts

import pyfect as fx
from pyfect import testing
from pyfect.chat import chat, chat_test
from pyfect.chat.chat_error import TooLarge
from pyfect.chat.chat_ui import Button
from pyfect.chat.teams import _adapter, _length, teams_chat
from pyfect.chat.teams._cloud import Unverified

THREAD = teams_chat.thread(CONVERSATION)


def rules() -> dict[str, chat_test.Rule]:
    return chat_test.conformance(
        platform="teams",
        thread=THREAD,
        user_posts=user_posts,
        parse_mention=teams_chat.parse_mention,
    )


@pytest.mark.parametrize("name", list(rules()))
@testing.effect
def test_conformance_over_the_stubbed_connector(name: str):
    """conformance over the stubbed Connector / {name}"""
    return rules()[name].pipe(fx.provide(teams_layer(Bot())))


@testing.effect
def test_get_thread_sends_its_query_and_accepts_the_answer():
    """reads over the stubbed Connector / getThread sends its query and accepts the answer"""
    bot = Bot()

    @fx.gen
    def program() -> Gen[None]:
        service = yield from chat.Chat()
        info = yield from service.get_thread(THREAD)
        assert info.kind == "channel"
        [read] = [sent for sent in bot.sent if sent.method == "GET"]
        assert read.url.search == "?pageSize=1"

    return program.pipe(fx.provide(teams_layer(bot)))


@testing.effect
def test_counts_the_signed_envelope_against_action_data_length():
    """buttons over the stubbed Connector / counts the signed envelope against actionDataLength"""
    buttons = teams_layer(
        Bot(), interaction_keys=[INTERACTION_KEY], unverified=Unverified(buttons=True)
    )

    @fx.gen
    def program() -> Gen[None]:
        service = yield from chat.Chat()
        # The raw id and value fit the cap; with the envelope they do not.
        over = Button(id="b", label="B", value="v" * (_adapter.ACTION_DATA_LENGTH - 1))
        error = yield from service.post(THREAD, markdown="x", actions=[over]).flip()
        assert isinstance(error.reason, TooLarge)
        fits = Button(id="b", label="B", value="v" * 400)
        posted = yield from service.post(THREAD, markdown="x", actions=[fits])
        assert isinstance(posted.id, str)

    return program.pipe(fx.provide(buttons))


@testing.effect
def test_a_private_answer_names_its_recipient_by_id_alone_so_it_stays_in_the_size_bound():
    """command answers over the stubbed Connector / a private answer names its recipient by id
    alone, so it stays in the size bound"""
    bot = Bot()

    @fx.gen
    def program() -> Gen[None]:
        service = yield from teams_chat.TeamsChat()
        raw = {
            "type": "message",
            "id": "1",
            "serviceUrl": "https://smba.trafficmanager.net/teams",
            "from": {"id": "29:user", "aadObjectId": "user", "name": "n" * 10_000},
            "conversation": {"id": CONVERSATION},
        }
        answer = service._interactions.answer  # pyright: ignore[reportPrivateUsage]
        yield from answer("respond", raw, "a" * _length.MESSAGE_LENGTH, (), "ephemeral")
        [sent] = [sent for sent in bot.sent if sent.url.search == "?isTargetedActivity=true"]
        assert json.loads(sent.body)["recipient"] == {"id": "29:user"}
        assert len(sent.body) <= _length.EDGE

    return program.pipe(fx.provide(teams_layer(bot)))
