"""Layer cases of ``pyfect.chat``: each run posts to the in-memory platform,
handles an event or answers a click."""

from __future__ import annotations

from typing import Any

import pyfect as fx
from layer_cases._case import Case
from pyfect import layer as L
from pyfect.chat import chat, chat_adapter, chat_handler, chat_test, chat_thread
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat import Chat
from pyfect.chat.chat_adapter import Registry
from pyfect.chat.chat_test import ChatTest

type AnyEffect = fx.Effect[Any, Any, Any]

_GO = ci.button("go", label="Go")


@fx.gen
def _posts():
    test = yield from ChatTest()
    thread = yield from test.make_thread()
    yield from (yield from Chat()).post(thread, markdown="hello")
    if len((yield from test.messages(thread))) != 1:
        return (yield from fx.die(AssertionError("one message per run")))
    return None


@fx.gen
def _handles():
    test = yield from ChatTest()
    thread = yield from test.make_thread()
    yield from test.deliver((yield from test.user_posts(thread, text="hi")))


@fx.gen
def _clicks():
    test = yield from ChatTest()
    thread = yield from test.make_thread()
    posted = yield from (yield from Chat()).post(thread, markdown="go?", actions=[_GO.of()])
    reply = yield from test.interact((yield from test.click(posted.id, "go")))
    if reply != ci.ack:
        return (yield from fx.die(AssertionError(reply)))
    return None


def _registered_again() -> AnyEffect:
    # Registers the test platform's adapter again, read from the registry.
    return Registry().flat_map(lambda registry: registry.get("test"))


CASES: dict[str, Case] = {
    "pyfect.chat.chat_test.layer": Case(layer=chat_test.layer, use=lambda: _posts),
    "pyfect.chat.chat.layer": Case(
        layer=lambda: chat.layer, use=lambda: Chat().map(lambda _: None)
    ),
    "pyfect.chat.chat_adapter.layer": Case(
        layer=lambda: chat_adapter.layer(_registered_again()),
        needs=chat_test.layer,
        use=lambda: _posts,
    ),
    "pyfect.chat.chat_handler.layer": Case(
        layer=lambda: chat_handler.layer(lambda _: fx.void),
        needs=chat_test.layer,
        use=lambda: _handles,
    ),
    "pyfect.chat.chat_interaction.layer": Case(
        layer=ci.layer, use=lambda: ci.Handler().flat_map(lambda h: h.click(_click()))
    ),
    "pyfect.chat.chat_interaction.Group.to_layer": Case(
        layer=lambda: (
            ci.group(_GO)
            .to_layer(_GO.handler(lambda _: fx.succeed(ci.ack)))
            .pipe(L.provide_merge(ci.layer()))
        ),
        needs=chat_test.layer,
        use=lambda: _clicks,
    ),
}


def _click() -> ci.ButtonClicked:
    thread = chat_thread.make("test", "c1")
    return ci.ButtonClicked(id="go", thread=thread, message_id="m1", user_id="u1", raw=None)


SKIPPED: dict[str, str] = {}
