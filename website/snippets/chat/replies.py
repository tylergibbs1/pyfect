from typing import Never

import pyfect as fx
from pyfect import stream
from pyfect.chat import chat_handler, chat_markdown, chat_test
from pyfect.chat.chat import Chat
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.chat.chat_test import ChatTest


# The handler answers every message with a reply split to the platform's limits.
def on_event(event: ChatEvent) -> fx.Effect[None, Never, Chat]:
    if not isinstance(event, MessageCreated):
        return fx.void
    report = "\n\n".join(f"Step {i}: done." for i in range(1, 6))
    return chat_markdown.post(event.thread, report).as_void().or_die()


@fx.gen
def program():
    test = yield from ChatTest()
    thread = yield from test.make_thread()
    yield from test.deliver((yield from test.user_posts(thread, text="status?")))
    for message in (yield from test.messages(thread)):
        print(repr(message.text))

    # Deltas from a model stream in as they arrive: one message, edited as it grows.
    deltas = stream.from_iterable(["Thinking", " about it", "...\n\nDone."])
    result = yield from chat_markdown.stream(thread, deltas)
    print([(part.transport, part.text) for part in result.parts])


app = program.pipe(fx.provide(chat_handler.layer(on_event))).pipe(
    fx.provide(chat_test.layer(message_length=40))
)
fx.run_blocking(app.or_die())
