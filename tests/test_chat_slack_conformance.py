"""Port of Effect's ``packages/chat/slack/test/conformance.test.ts``: the
conformance rules against the adapter over a stubbed Web API that keeps what
was posted. Clicks, submits and commands are built from the posted blocks and
the opened views and go through ``SlackChatService.interaction``."""

from __future__ import annotations

import pytest
from _slack_fake import CHANNEL, TEAM, Slack, slack_layer

import pyfect as fx
from pyfect import testing
from pyfect.chat import chat_test
from pyfect.chat.slack import slack_chat

# Rules that need a user's message, a thread's history or a stored file,
# which the stub does not keep: Effect's live suite runs them.
LIVE_ONLY = {
    "post/files",
    "download/maxBytes",
    "history/sameAsInbound",
    "message/threadStable",
    "inbound/fetchable",
    "inbound/notSelf",
    "nativeStream/concatenates",
    "nativeStream/appendAfterStop",
    "unsupported/getUser",
}

THREAD = slack_chat.thread(team=TEAM, channel=CHANNEL)


def rules(slack: Slack | None) -> dict[str, chat_test.Rule]:
    return chat_test.conformance(
        platform="slack",
        thread=THREAD,
        user_posts=lambda _thread, _text: fx.die("unused"),
        parse_mention=slack_chat.parse_mention,
        refuse_files=(lambda: fx.void) if slack is None else slack.refuse_files,
        interactions=chat_test.Interactions(
            click=lambda _m, _i, _o: fx.void,
            submit=lambda _v: fx.void,
            command=lambda _t, _i, _x: fx.void,
        )
        if slack is None
        else slack.interactions,
    )


NAMES = [name for name in rules(None) if name not in LIVE_ONLY]


@pytest.mark.parametrize("name", NAMES)
@testing.effect
def test_conformance_over_the_stubbed_web_api(name: str):
    """conformance over the stubbed Web API / {name}"""
    slack = Slack()
    return slack.bind.flat_map(lambda _: rules(slack)[name]).pipe(
        fx.provide(slack_layer(slack.fake))
    )
