"""Every call of a persisted chat saves it, as Effect's ``Chat.makePersisted``
wraps ``generateText`` / ``generateObject`` in ``Effect.ensuring(saveChat)`` and
``streamText`` in ``Stream.ensuring(saveChat)``.

The guard below lists ``Chat.Service``'s public call methods and fails when one
has no case here, so a new call cannot skip the save unnoticed.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypedDict

import pytest
from oracle._ai import with_language_model

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.ai import chat as C
from pyfect.ai import prompt as P
from pyfect.persistence import persistence
from pyfect.persistence.persistence import BackingPersistence

PERSISTENCE = C.layer_persisted(store_id="chat").pipe(
    layer.provide_merge(persistence.layer_backing_memory)
)

TEXT = [{"type": "text", "text": "hello"}]
STREAMED = [
    {"type": "text-start", "id": "t"},
    {"type": "text-delta", "id": "t", "delta": "hello"},
    {"type": "text-end", "id": "t"},
]


def _generate_text(chat: C.Service) -> fx.Effect[object, Any, Any]:
    return chat.generate_text("hi").pipe(with_language_model(generate_text=TEXT))


class _Answer(TypedDict):
    a: int


def _generate_object(chat: C.Service) -> fx.Effect[object, Any, Any]:
    answer = [{"type": "text", "text": '{"a":1}'}]
    return chat.generate_object("hi", schema=S.Struct(_Answer)).pipe(
        with_language_model(generate_text=answer)
    )


def _stream_text(chat: C.Service) -> fx.Effect[object, Any, Any]:
    return chat.stream_text("hi").run_drain().pipe(with_language_model(stream_text=STREAMED))


CALLS: dict[str, Callable[[C.Service], fx.Effect[object, Any, Any]]] = {
    "generate_text": _generate_text,
    "generate_object": _generate_object,
    "stream_text": _stream_text,
}


def test_every_call_method_of_a_chat_has_a_case():
    methods = {
        name
        for name, _ in inspect.getmembers(C.Service, inspect.isfunction)
        if name.startswith(("generate_", "stream_"))
    }
    assert methods == set(CALLS)


@pytest.mark.parametrize("name", list(CALLS))
@testing.effect
def test_a_persisted_chat_saves_after_each_call(name: str):
    def body():
        chats = yield from C.Persistence()
        chat = yield from chats.get_or_create("1")
        yield from CALLS[name](chat)
        backing = yield from BackingPersistence()
        stored = yield from (yield from backing.make("chat")).get("1")
        assert stored is not None
        decoded = yield from S.decode_unknown_effect(P.Prompt)(stored)
        assert [m.role for m in decoded.content] == ["user", "assistant"]
        assert decoded == (yield from chat.history.get())

    yield from fx.gen(body).pipe(fx.provide(PERSISTENCE))
