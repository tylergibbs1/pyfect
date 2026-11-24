"""``teams_chat.escape_markdown``: user text, such as a display name, put
into a post shows as typed. A dogfood app's display name was a live link."""

from __future__ import annotations

import json

from _literal_markdown import literal
from _teams_fake import CONVERSATION, Bot, Gen, teams_layer

import pyfect as fx
from pyfect import testing
from pyfect.chat import chat
from pyfect.chat.teams import teams_chat

THREAD = teams_chat.thread(CONVERSATION)

UNTRUSTED = [
    "[x](http://evil)",
    "![x](http://evil/i.png)",
    "<http://evil>",
    "*bold* __strong__ _it_ ~~gone~~ `code`",
    "<b>&amp;</b>",
    "back\\slash \\[x\\](http://evil)",
    "$x$",
    "Ada L. (ops) #1",
]
"""Display names a user picks; all but the last form syntax unescaped."""


def sent_text(markdown: str) -> Gen[str]:
    bot = Bot()
    yield from (
        chat.Chat()
        .flat_map(lambda service: service.post(THREAD, markdown=markdown))
        .pipe(fx.provide(teams_layer(bot)))
    )
    [posted] = [
        sent for sent in bot.sent if sent.method == "POST" and "/activities" in sent.url.href
    ]
    return json.loads(posted.body)["text"]


@testing.effect
def test_escape_markdown_keeps_user_text_literal_in_what_teams_is_sent():
    @fx.gen
    def program() -> Gen[None]:
        for name in UNTRUSTED:
            text = yield from sent_text(f"Deploy by {teams_chat.escape_markdown(name)}.")
            assert literal(text) == f"Deploy by {name}.", name

    return program


@testing.effect
def test_unescaped_user_text_forms_a_link():
    @fx.gen
    def program() -> Gen[None]:
        text = yield from sent_text("Deploy by [x](http://evil).")
        assert literal(text) is None

    return program


def test_escape_markdown_leaves_text_without_syntax_alone():
    """Adaptive Cards show a backslash before most punctuation, so only
    the characters that form inline syntax are escaped."""
    assert teams_chat.escape_markdown("Ada L. (ops) #1 - on call!") == "Ada L. (ops) #1 - on call!"
