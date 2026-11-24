from typing import TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.chat import chat_interaction as ci
from pyfect.chat import chat_test
from pyfect.chat.chat import Chat
from pyfect.chat.chat_test import ChatTest


class Deploy(TypedDict):
    version: str


# A button whose value is typed: the click handler gets a Deploy, decoded.
approve = ci.button("approve", label="Approve", value=S.Struct(Deploy))


def on_approve(click: ci.Click[Deploy]) -> fx.Effect[ci.ClickReply]:
    return fx.sync(lambda: print("approved", click.value["version"], "by", click.user_id)).as_(
        ci.ack
    )


interactions = (
    ci.group(approve).to_layer(approve.handler(on_approve)).pipe(layer.provide_merge(ci.layer()))
)


@fx.gen
def program():
    chat = yield from Chat()
    test = yield from ChatTest()
    thread = yield from test.make_thread()
    posted = yield from chat.post(
        thread, markdown="Ship v1.4.2?", actions=[approve.of({"version": "v1.4.2"})]
    )
    # The test platform clicks the button and runs the handler within the 3 second deadline.
    click = yield from test.click(posted.id, "approve", user_id="U42")
    print((yield from test.interact(click)))


fx.run_blocking(program.pipe(fx.provide(interactions)).pipe(fx.provide(chat_test.layer())).or_die())
