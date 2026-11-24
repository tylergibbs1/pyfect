"""``slack_chat.escape_markdown``: user text, such as a display name, put
into a post shows as typed in the ``markdown`` block and notifies nobody
from the ``text``, whatever the post options let notify."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

from _literal_markdown import literal
from _slack_fake import CHANNEL, TEAM, Fake, slack_layer

import pyfect as fx
from pyfect import testing
from pyfect._core import Effect
from pyfect.chat import chat
from pyfect.chat.slack import slack_chat
from pyfect.chat.slack._options import SlackPostOptions

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

THREAD = slack_chat.thread(team=TEAM, channel=CHANNEL)
EVERYONE = SlackPostOptions(notify_users=["U1"], notify_groups=["S1"], notify_broadcast=True)

UNTRUSTED = [
    "<!channel>",
    "<@U1>",
    "<!subteam^S1>",
    "*bold* **strong** _it_ ~x~ ~~gone~~ `code`",
    "<http://evil|click>",
    "[x](http://evil)",
    "a &amp; b &lt;@U1&gt;",
    "back\\slash \\<@U1>",
    "# not a heading",
    "Ada L. (ops) #1",
]
"""Display names a user picks; all but the last form syntax unescaped."""


def sent(markdown: str, options: SlackPostOptions) -> Gen[tuple[str, str]]:
    """The ``markdown`` block's text and the ``text`` the post sends."""
    fake = Fake({"chat.postMessage": {"ok": True, "channel": CHANNEL, "ts": "1794600000.000100"}})
    yield from (
        chat.Chat()
        .flat_map(lambda service: service.post(THREAD, markdown=markdown))
        .pipe(slack_chat.with_post_options(options))
        .pipe(fx.provide(slack_layer(fake)))
    )
    [call] = fake.called("chat.postMessage")
    [block] = json.loads(call.params["blocks"])
    assert block["type"] == "markdown"
    return block["text"], call.params["text"]


@testing.effect
def test_escape_markdown_keeps_user_text_literal_in_what_slack_is_sent():
    @fx.gen
    def program() -> Gen[None]:
        for options in (SlackPostOptions(), EVERYONE):
            for name in UNTRUSTED:
                block, text = yield from sent(
                    f"Deploy by {slack_chat.escape_markdown(name)}.", options
                )
                assert literal(block) == f"Deploy by {name}.", name
                assert "<" not in text, name

    return program


@testing.effect
def test_unescaped_user_text_notifies_when_the_options_allow_it():
    @fx.gen
    def program() -> Gen[None]:
        block, text = yield from sent("Deploy by <!channel>.", EVERYONE)
        assert "<!channel>" in block
        assert "<!channel>" in text

    return program


def test_escape_markdown_leaves_text_without_syntax_alone():
    assert slack_chat.escape_markdown("Ada L. (ops) - on call!") == "Ada L. (ops) - on call!"
