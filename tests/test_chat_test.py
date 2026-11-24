"""Port of Effect's ``test/chat/ChatTest.test.ts``: the fake adapter passes
its own conformance suite, with every capability, with none, and with the
combinations all-on and all-off miss."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect._core import Effect
from pyfect.chat import chat_handler, chat_test, chat_thread
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat import Chat
from pyfect.chat.chat_adapter import ChatAdapter, Descriptor, Registry
from pyfect.chat.chat_error import CAPABILITIES, FILE_REFUSED, Capability, ChatError, Forbidden
from pyfect.chat.chat_error import Unsupported as UnsupportedReason
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.chat.chat_message import (
    Author,
    Mention,
    ReplyTo,
    mentions_self,
    replies_to_self,
)
from pyfect.chat.chat_test import ChatTest, MentionToken
from pyfect.chat.chat_thread import ChatThread
from pyfect.exit import Failure

_KINDS = {"@": "user", "@&": "role", "#": "channel", "!": "broadcast"}
_TOKEN = re.compile(r"^<(@&|@|#|!)([^<>\s]+)>$")


def parse_mention(slice: str) -> MentionToken | None:
    match = _TOKEN.match(slice)
    if match is None:
        return None
    return MentionToken(_KINDS[match.group(1)], match.group(2))  # pyright: ignore[reportArgumentType]


@dataclass
class _Open:
    from_: ci.ButtonClicked | ci.SelectChanged | ci.CommandInvoked
    opened: ci.OpenModal


def interactions_for(test: chat_test.Service) -> chat_test.Interactions:
    """The conformance click hook, over the fake's own entry."""
    state: list[_Open | None] = [None]

    def deliver(
        from_: ci.ButtonClicked | ci.SelectChanged | ci.CommandInvoked,
    ) -> Effect[None, Any, ci.Handler]:
        @fx.gen
        def run() -> Generator[Effect[Any, Any, Any], Any]:
            handler = yield from ci.Handler()
            refused = [False]

            def on_refused(
                event: ci.ButtonClicked | ci.SelectChanged | ci.CommandInvoked, error: ChatError
            ) -> Effect[None]:
                return fx.sync(lambda: refused.__setitem__(0, True)).and_then(
                    handler.refused(event, error)
                )

            watching = ci.HandlerService(
                click=handler.click,
                submit=handler.submit,
                command=handler.command,
                refused=on_refused,
            )
            reply = yield from test.interact(from_).pipe(fx.provide_service(ci.Handler, watching))
            state[0] = (
                _Open(from_, reply) if isinstance(reply, ci.OpenModal) and not refused[0] else None
            )

        return run

    def submit(values: Mapping[str, str]) -> Effect[None, Any, ci.Handler]:
        @fx.gen
        def run() -> Generator[Effect[Any, Any, Any], Any]:
            current = state[0]
            if current is None:
                return
            event = yield from test.submit(current.from_, current.opened, values)
            reply = yield from test.interact(event)
            if not isinstance(reply, ci.Errors):
                state[0] = None

        return run

    return chat_test.Interactions(
        click=lambda message_id, id, option: test.click(message_id, id, option=option).flat_map(
            deliver
        ),
        command=lambda thread, id, text: test.command(thread, id, text=text).flat_map(deliver),
        submit=submit,
    )


def rules_for(test: chat_test.Service, thread: ChatThread) -> dict[str, chat_test.Rule]:
    return chat_test.conformance(
        platform=test.platform,
        thread=thread,
        user_posts=lambda thread, text: test.user_posts(thread, text=text),
        parse_mention=parse_mention,
        refuse_files=test.refuse_files,
        fail_next=test.fail_next,
        interactions=interactions_for(test),
    )


@fx.gen
def suite() -> Generator[Effect[Any, Any, Any], Any, dict[str, chat_test.Rule]]:
    test = yield from ChatTest()
    thread = yield from test.make_thread()
    return rules_for(test, thread)


RULE_NAMES = list(
    chat_test.conformance(
        platform="test",
        thread=chat_thread.make("test", "c0"),
        user_posts=lambda _thread, _text: fx.die("unused"),
        parse_mention=parse_mention,
        refuse_files=lambda: fx.void,
        fail_next=lambda _op, _reason: fx.void,
        interactions=chat_test.Interactions(
            click=lambda _m, _i, _o: fx.void,
            submit=lambda _v: fx.void,
            command=lambda _t, _i, _x: fx.void,
        ),
    )
)


def run_rule(rule: str, capabilities: Sequence[Capability] = CAPABILITIES) -> Effect[None, Any]:
    return suite.flat_map(lambda rules: rules[rule]).pipe(
        fx.provide(chat_test.layer(capabilities=capabilities))
    )


@testing.effect
def test_allows_a_post_when_the_fault_count_is_zero():
    @fx.gen
    def program():
        test = yield from ChatTest()
        chat = yield from Chat()
        thread = yield from test.make_thread()
        yield from test.fail_next("post", Forbidden(detail="zero-count fault"), times=0)
        yield from chat.post(thread, markdown="hello")

    return program.pipe(fx.provide(chat_test.layer()))


@pytest.mark.parametrize("rule", RULE_NAMES)
@testing.live
def test_conformance_with_every_capability(rule: str):
    return run_rule(rule)


# With a capability off, a gated rule only probes it, as unsupported/{capability} does.
@pytest.mark.parametrize("rule", [name for name in RULE_NAMES if name.startswith("unsupported/")])
@testing.live
def test_conformance_without_any_capability(rule: str):
    return run_rule(rule, ())


# Paths that all-on and all-off miss: a probe gated on another capability, and a modal opened
# from a select.
@pytest.mark.parametrize(
    ("rule", "off"),
    [
        ("modal/origin", "buttons"),
        ("unsupported/modals", "modals"),
        ("modal/errorsKeepOpen", "modalErrors"),
        ("unsupported/ephemeral", "ephemeral"),
    ],
)
@testing.live
def test_conformance_rule_without_one_capability(rule: str, off: str):
    return run_rule(rule, tuple(c for c in CAPABILITIES if c != off))


def test_lists_the_hook_rules_only_with_their_hooks():
    without_hooks = list(
        chat_test.conformance(
            platform="test",
            thread=chat_thread.make("test", "c0"),
            user_posts=lambda _thread, _text: fx.die("unused"),
            parse_mention=parse_mention,
        )
    )
    assert "unsupported/buttons" in without_hooks
    for name in [
        "post/refusedFile",
        "actions/valueRoundTrips",
        "command/arrives",
        "retries/retrySafe",
    ]:
        assert name not in without_hooks
        assert name in RULE_NAMES


class _Override:
    """An adapter with some members replaced, as ``{ ...adapter, ... }``."""

    def __init__(self, adapter: ChatAdapter, **members: Any) -> None:
        self._adapter = adapter
        self._members = members

    def __getattr__(self, name: str) -> Any:
        return self._members[name] if name in self._members else getattr(self._adapter, name)


@testing.effect
def test_fails_unsupported_capability_for_a_descriptor_that_leaves_out_a_working_op():
    @fx.gen
    def program():
        registry = yield from Registry()
        adapter = yield from registry.get("test")
        listed = adapter.descriptor.capabilities - {"edit"}
        descriptor = Descriptor(
            platform=adapter.descriptor.platform,
            capabilities=listed,
            measure=adapter.descriptor.measure,
            limits=adapter.descriptor.limits,
        )
        yield from registry.register(_Override(adapter, descriptor=descriptor))  # pyright: ignore[reportArgumentType]
        failure = yield from suite.flat_map(lambda rules: rules["unsupported/edit"]).flip()
        assert failure.rule == "unsupported/edit"
        assert failure.actual == "success"

    return program.pipe(fx.provide(chat_test.layer()))


@testing.effect
def test_fails_a_rule_whose_listed_capability_fails_with_unsupported():
    @fx.gen
    def program():
        registry = yield from Registry()
        adapter = yield from registry.get("test")
        refuse = fx.fail(
            ChatError(platform="test", op="edit", reason=UnsupportedReason(capability="edit"))
        )

        def edit(*_args: object, **_kwargs: object) -> Effect[None, ChatError]:
            return refuse

        yield from registry.register(_Override(adapter, edit=edit))  # pyright: ignore[reportArgumentType]
        failure = yield from suite.flat_map(lambda rules: rules["edit/keepsId"]).flip()
        assert failure.actual == "Unsupported(edit) for a listed capability"

    return program.pipe(fx.provide(chat_test.layer()))


@testing.effect
def test_post_refused_file_cleans_up_a_refused_write_that_landed():
    @fx.gen
    def program():
        test = yield from ChatTest()
        thread = yield from test.make_thread()
        rules = chat_test.conformance(
            platform=test.platform,
            thread=thread,
            parse_mention=parse_mention,
            user_posts=lambda thread, text: test.user_posts(thread, text=text),
            refuse_files=lambda: test.fail_next(
                "post", Forbidden(detail=FILE_REFUSED), landed=True
            ),
        )
        error = yield from rules["post/refusedFile"].flip()
        assert error.expected == "no new message"
        assert (yield from test.messages(thread)) == ()

    return program.pipe(fx.provide(chat_test.layer()))


@testing.live
def test_deletes_every_bot_message_the_suite_posts():
    @fx.gen
    def program():
        test = yield from ChatTest()
        thread = yield from test.make_thread()
        yield from fx.for_each(
            list(rules_for(test, thread).values()), lambda rule: rule, discard=True
        )
        left = [m for m in (yield from test.messages(thread)) if m.author.is_self]
        assert [m.text for m in left] == []

    return program.pipe(fx.provide(chat_test.layer()))


@testing.effect
def test_check_interaction_rejects_an_empty_message_id():
    submitted = ci.ModalSubmitted(
        id="ask",
        values={},
        thread=chat_thread.make("test", "c1"),
        message_id="",
        user_id="u",
        raw=None,
    )

    @fx.gen
    def program():
        failure = yield from chat_test.check_interaction(submitted, platform="test").flip()
        assert failure.actual == "an empty message_id"

    return program


@testing.effect
def test_replies_to_self_only_for_replies_to_the_bot_check_message_rejects_bad_ones():
    """repliesToSelf is true only for a reply to the bot's message; checkMessage rejects
    bad replyTo and mentions."""

    @fx.gen
    def program():
        test = yield from ChatTest()
        chat = yield from Chat()
        thread = yield from test.make_thread()
        own = yield from chat.post(thread, markdown="from the bot")
        plain = (yield from test.user_posts(thread, text="no reply")).message
        to_bot = (
            yield from test.user_posts(
                thread, text="to the bot", reply_to=ReplyTo(message_id=own.id)
            )
        ).message
        to_user = (
            yield from test.user_posts(
                thread, text="to a person", reply_to=ReplyTo(message_id=plain.id)
            )
        ).message
        assert [replies_to_self(m) for m in (plain, to_bot, to_user)] == [False, True, False]
        assert not mentions_self(to_bot)
        # check_message rejects an author without is_self, and is_self without an author.
        for reply_to in (
            ReplyTo(message_id=own.id, author_id=test.self_id),
            ReplyTo(message_id=own.id, is_self=True),
        ):
            exit = yield from chat_test.check_message(
                copy.replace(to_bot, reply_to=reply_to),
                platform="test",
                parse_mention=parse_mention,
            ).exit()
            assert isinstance(exit, Failure)
        # It also rejects a mention whose slice is not its token.
        mentioning = (yield from test.user_posts(thread, text="hi", mentions_self=True)).message
        yield from chat_test.check_message(mentioning, platform="test", parse_mention=parse_mention)
        shifted = copy.replace(
            mentioning,
            mentions=tuple(
                Mention(kind=m.kind, id=m.id, start=m.start + 1, end=m.end, is_self=m.is_self)
                for m in mentioning.mentions
            ),
        )
        exit = yield from chat_test.check_message(
            shifted, platform="test", parse_mention=parse_mention
        ).exit()
        assert isinstance(exit, Failure)

    return program.pipe(fx.provide(chat_test.layer()))


@testing.effect
def test_chat_handler_layer_drops_the_bots_own_messages_unless_deliver_self():
    @fx.gen
    def program():
        test = yield from ChatTest()
        thread = yield from test.make_thread()
        own = yield from test.user_posts(thread, text="own")
        author = own.message.author
        self_event = MessageCreated(
            thread=own.thread,
            kind=own.kind,
            message=copy.replace(
                own.message,
                author=Author(id=author.id, name=author.name, is_bot=author.is_bot, is_self=True),
            ),
            raw=own.raw,
        )
        received: list[str] = []

        def record(prefix: str) -> Callable[[ChatEvent], Effect[None]]:
            def handle(event: ChatEvent) -> Effect[None]:
                return fx.sync(lambda: received.append(prefix + type(event).__name__))

            return handle

        handler = chat_handler.layer(record(""))
        yield from test.deliver(self_event).pipe(fx.provide(handler))
        yield from test.deliver(own).pipe(fx.provide(handler))
        yield from test.deliver(self_event).pipe(
            fx.provide(chat_handler.layer(record("self "), deliver_self=True))
        )
        assert received == ["MessageCreated", "self MessageCreated"]

    return program.pipe(fx.provide(chat_test.layer()))
