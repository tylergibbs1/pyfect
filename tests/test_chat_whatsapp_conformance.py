"""Port of Effect's ``packages/chat/whatsapp/test/conformance.test.ts``: the
conformance rules against the adapter over a fake Graph API that keeps what
was sent. Clicks are built from the sent reply buttons and list rows and go
through ``WhatsAppChatService.receive``."""

from __future__ import annotations

import pytest
from _whatsapp_fake import THREAD, Clicks, Graph, user_posts, whatsapp_layer

import pyfect as fx
from pyfect import testing
from pyfect.chat import chat_test
from pyfect.chat.whatsapp import whatsapp_chat


def rules(clicks: Clicks | None) -> dict[str, chat_test.Rule]:
    return chat_test.conformance(
        platform="whatsapp",
        thread=THREAD,
        user_posts=user_posts,
        parse_mention=whatsapp_chat.parse_mention,
        interactions=chat_test.Interactions(
            click=lambda _m, _i, _o: fx.void, submit=lambda _v: fx.void
        )
        if clicks is None
        else clicks.interactions,
    )


NAMES = list(rules(None))


@pytest.mark.parametrize("name", NAMES)
@testing.effect
def test_conformance_over_a_fake_graph_api(name: str):
    """conformance over a fake Graph API / {name}"""
    graph = Graph()
    clicks = Clicks(graph)
    return clicks.bind.flat_map(lambda _: rules(clicks)[name]).pipe(
        fx.provide(whatsapp_layer(graph))
    )
