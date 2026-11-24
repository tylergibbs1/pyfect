"""The rules of ``chat_test.conformance``, by name (Effect's rule names, so
a failure reads the same in both)."""

from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from typing import Any, Literal

import pyfect as fx
from pyfect import _json_text
from pyfect import date_time as _date_time
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.chat import chat as _chat
from pyfect.chat import chat_interaction as ci
from pyfect.chat import chat_thread
from pyfect.chat import chat_ui as U
from pyfect.chat._chat_conformance import (
    MEASURE_FITS_BLOCK,
    MEASURE_SAMPLES,
    MENTION_LIKE,
    PROBE_MODAL,
    TEXT_TOO_LARGE,
    VALUE_CASES,
    ConformanceFailure,
    Created,
    Interactions,
    NoSuchElement,
    Options,
    ParseMention,
    Tester,
    Version,
    canonical_json,
    check_event,
    conformance_button,
    conformance_file,
    conformance_select,
    conformance_text,
    describe_error,
    describe_exit,
    error_of,
    failure,
    first_missing,
    largest_fitting,
    same_message,
    same_value,
)
from pyfect.chat.chat_adapter import AppendResult, Descriptor, NativeStream, Posted, Registry
from pyfect.chat.chat_error import (
    CAPABILITIES,
    FILE_REFUSED,
    AnyReason,
    Capability,
    ChatError,
    RateLimited,
    Transport,
    Unsupported,
)
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.chat.chat_message import ChatMessage, ReplyTo
from pyfect.chat.chat_thread import ChatThread
from pyfect.duration import millis
from pyfect.exit import Exit, Success

type Rule = Effect[None, ConformanceFailure, _chat.Chat | Registry]
"""One conformance rule: it needs the adapter under test registered in
``Chat``."""

type _Body = Callable[[Tester], Effect[None, ConformanceFailure, Registry]]
type _Gen[A] = Generator[Effect[Any, ConformanceFailure, Any], Any, A]


def conformance(
    *,
    platform: str,
    thread: ChatThread,
    user_posts: Callable[[ChatThread, str], Effect[ChatEvent]],
    parse_mention: ParseMention,
    refuse_files: Callable[[], Effect[None]] | None = None,
    interactions: Interactions | None = None,
    fail_next: Callable[[str, AnyReason], Effect[None]] | None = None,
) -> dict[str, Rule]:
    """The conformance suite, as plain effects keyed by rule name, so any
    test runner can run them.

    - Each rule needs the adapter under test registered in ``Chat``, and
      ``user_posts`` to make another identity's message appear in
      ``thread``, a channel the suite may write to.
    - A rule is never skipped. When the descriptor lacks a capability a rule
      needs, the rule becomes its inverse: the op fails ``Unsupported``.
      There is an ``unsupported/{capability}`` rule for every capability;
      with the capability listed it fails if the op fails ``Unsupported``.
    - The ``retries/*`` rules exist only with ``fail_next``,
      ``post/refusedFile`` only with ``refuse_files``, the click rules only
      with ``interactions``, and the ``command/*`` rules and
      ``unsupported/ephemeral`` only with ``interactions.command``.
    - Every rule deletes what it posted when it ends, pass or fail, when
      the platform can delete.

    Rule names are stable and an existing rule is never tightened. The
    ``retries/retrySafe`` rule waits for real time, so run the suite on a
    live ``Clock``.
    """
    options = Options(
        platform=platform,
        thread=thread,
        user_posts=user_posts,
        parse_mention=parse_mention,
        refuse_files=refuse_files,
        interactions=interactions,
        fail_next=fail_next,
    )
    rules: dict[str, Rule] = {}

    def rule(name: str, needs: Sequence[Capability], body: _Body) -> None:
        @fx.gen
        def run() -> Generator[Effect[Any, ConformanceFailure, Any], Any]:
            chat: _chat.Service = yield from _chat.Chat()
            descriptor: Descriptor = yield from chat.descriptor(platform).map_error(
                lambda error: failure(name, "a registered adapter", describe_error(error), error)
            )
            t = Tester(name, chat, descriptor, options)
            missing = first_missing(needs, descriptor.capabilities)
            yield from (body(t) if missing is None else t.probe(missing)).ensuring(t.cleanup)

        rules[name] = run

    _post_rules(rule, options)
    _message_rules(rule)
    _stream_rules(rule, options)
    _action_rules(rule)
    if interactions is not None:
        _click_rules(rule)
    if interactions is not None and interactions.command is not None:
        _command_rules(rule)
    for capability in CAPABILITIES:
        if capability not in ("modals", "modalErrors", "ephemeral"):
            rule(f"unsupported/{capability}", [], _probe(capability))
    if fail_next is not None:
        _retry_rules(rule, fail_next)
    return rules


def _probe(capability: Capability) -> _Body:
    return lambda t: t.probe(capability)


type _AddRule = Callable[[str, Sequence[Capability], _Body], None]


def _ids(messages: Sequence[ChatMessage]) -> str:
    return ",".join(m.id for m in messages)


def _find_in(messages: Sequence[ChatMessage], id: str) -> ChatMessage | None:
    return next((m for m in messages if m.id == id), None)


def _gone_id(t: Tester) -> Effect[str, ConformanceFailure]:
    @fx.gen
    def run() -> _Gen[str]:
        posted: Posted = yield from t.post()
        if not t.has("delete"):
            return posted.id + "0"
        yield from t.call(t.chat.delete(t.thread, posted.id))
        return posted.id

    return run


def _post_rules(rule: _AddRule, options: Options) -> None:  # noqa: PLR0915
    def fetchable(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post()
            message: ChatMessage = yield from t.call(t.chat.fetch_message(t.thread, posted.id))
            yield from t.check(
                posted.id == message.id
                and chat_thread.equals(posted.thread, t.thread)
                and chat_thread.equals(message.thread, t.thread),
                f"the posted message, addressed to {chat_thread.to_string(t.thread)}",
                lambda: f"message {message.id} in {chat_thread.to_string(message.thread)}",
            )

        return run

    rule("post/fetchable", ["fetchMessage"], fetchable)

    def author_is_self(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post()
            message: ChatMessage = yield from t.call(t.chat.fetch_message(t.thread, posted.id))
            yield from t.check(
                message.author.is_self and message.author.is_bot,
                "author.is_self and author.is_bot",
                lambda: f"is_self {message.author.is_self}, is_bot {message.author.is_bot}",
            )

        return run

    rule("post/authorIsSelf", ["fetchMessage"], author_is_self)

    def reply_to(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            target: Posted = yield from t.post()
            reply: Posted = yield from t.post(reply_to=ReplyTo(message_id=target.id))
            message: ChatMessage = yield from t.call(t.chat.fetch_message(t.thread, reply.id))
            replied = None if message.reply_to is None else message.reply_to.message_id
            yield from t.check(
                replied == target.id, f"reply_to {target.id}", lambda: f"reply_to {replied}"
            )

        return run

    rule("post/replyTo", ["replyTo", "fetchMessage"], reply_to)

    def files(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            file = conformance_file(t.rule)
            posted: Posted = yield from t.post(files=(file,))
            message: ChatMessage = yield from t.call(t.chat.fetch_message(t.thread, posted.id))
            yield from t.check(
                len(message.attachments) == 1,
                "one attachment",
                lambda: str(len(message.attachments)),
            )
            chunks: list[bytes] = yield from t.collect(
                t.chat.download(t.thread, message.attachments[0], max_bytes=len(file.content))
            )
            content = b"".join(chunks)
            yield from t.check(
                content == file.content,
                "the uploaded bytes",
                lambda: f"{len(content)} different bytes",
            )

        return run

    rule("post/files", ["files", "download", "fetchMessage"], files)

    refuse_files = options.refuse_files
    if refuse_files is not None:
        refuse = refuse_files

        def refused_file(t: Tester) -> Effect[None, ConformanceFailure]:
            @fx.gen
            def run() -> _Gen[None]:
                history = t.chat.history(t.thread, direction="forward")
                before: list[ChatMessage] = yield from t.collect(history)
                yield from refuse()
                exit: Exit[Posted, ChatError] = yield from t.chat.post(
                    t.thread,
                    markdown=conformance_text(t.rule),
                    files=(conformance_file(t.rule),),
                ).exit()
                if isinstance(exit, Success):
                    t.track(exit.value)
                after: list[ChatMessage] = yield from t.collect(history)
                before_ids = {m.id for m in before}
                for message in after:
                    if (
                        message.author.is_self
                        and message.id not in before_ids
                        and not any(c.id == message.id for c in t.created)
                    ):
                        t.created.append(Created(message.thread, message.id))
                error = error_of(exit)
                reason = None if error is None else error.reason
                listed = isinstance(reason, Unsupported) and t.has(reason.capability)
                yield from t.check(
                    not listed
                    and reason is not None
                    and reason.retry == "denied"
                    and reason.detail == FILE_REFUSED,
                    "denied with detail file_refused, not Unsupported for a listed capability",
                    lambda: describe_exit(exit) + (" for a listed capability" if listed else ""),
                )
                yield from t.check(
                    [m.id for m in after] == [m.id for m in before],
                    "no new message",
                    lambda: f"{len(after)} messages after, {len(before)} before",
                )

            return run

        rule("post/refusedFile", ["files", "history"], refused_file)

    rule(
        "post/tooLarge",
        [],
        lambda t: t.expect_reason(
            "TooLarge",
            t.chat.post(t.thread, markdown="x" * (t.descriptor.limits.message_length + 1)),
            t.track,
            TEXT_TOO_LARGE,
        ),
    )

    def measure_fits(t: Tester) -> Effect[None, ConformanceFailure]:
        measure = t.descriptor.measure
        limit = t.descriptor.limits.message_length

        def largest(make: Callable[[int], str]) -> str:
            return make(largest_fitting(limit, lambda n: measure(make(n), ()) <= limit))

        blocks = largest(lambda n: MEASURE_FITS_BLOCK * n)
        markdown = largest(lambda n: blocks + "x" * n)
        return t.post(markdown=markdown).as_(None)

    rule("descriptor/measureFits", [], measure_fits)

    def measure_adds(t: Tester) -> Effect[None, ConformanceFailure]:
        measure = t.descriptor.measure

        @fx.gen
        def run() -> _Gen[None]:
            for a in MEASURE_SAMPLES:
                for b in MEASURE_SAMPLES:
                    yield from t.check(
                        measure(a + b, ()) <= measure(a, ()) + measure(b, ()),
                        "measure(a + b) <= measure(a) + measure(b)",
                        lambda a=a, b=b: (
                            f"{_json_text.quote(a)} + {_json_text.quote(b)} measures "
                            f"{measure(a + b, ())}"
                        ),
                    )
            letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
            yield from t.check(
                measure(letters, ()) == len(letters),
                "ASCII letters measured at one each",
                lambda: f"{len(letters)} letters measure {measure(letters, ())}",
            )

        return run

    rule("descriptor/measureAdds", [], measure_adds)

    def no_mentions(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post(markdown=MENTION_LIKE)
            message: ChatMessage = yield from t.call(t.chat.fetch_message(t.thread, posted.id))
            yield from t.check(
                len(message.mentions) == 0,
                "no mentions",
                lambda: f"{len(message.mentions)} mentions",
            )

        return run

    rule("post/noMentions", ["fetchMessage"], no_mentions)


def _message_rules(rule: _AddRule) -> None:  # noqa: PLR0915
    def keeps_id(t: Tester) -> Effect[None, ConformanceFailure]:
        text = conformance_text(t.rule)

        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post(markdown=text + " before")
            before: ChatMessage = yield from t.call(t.chat.fetch_message(t.thread, posted.id))
            yield from t.call(t.chat.edit(t.thread, posted.id, markdown=text + " after"))
            after: ChatMessage = yield from t.call(t.chat.fetch_message(t.thread, posted.id))
            yield from t.check(
                after.id == posted.id and after.text != before.text,
                "the same id with new text",
                lambda: (
                    f"id {after.id}" + (" with the old text" if after.text == before.text else "")
                ),
            )

        return run

    rule("edit/keepsId", ["edit", "fetchMessage"], keeps_id)
    rule(
        "edit/unknownId",
        ["edit"],
        lambda t: _gone_id(t).flat_map(
            lambda id: t.expect_reason(
                "NotFound", t.chat.edit(t.thread, id, markdown=conformance_text(t.rule))
            )
        ),
    )
    rule(
        "edit/tooLarge",
        ["edit"],
        lambda t: t.post().flat_map(
            lambda posted: t.expect_reason(
                "TooLarge",
                t.chat.edit(
                    t.thread, posted.id, markdown="x" * (t.descriptor.limits.message_length + 1)
                ),
                None,
                TEXT_TOO_LARGE,
            )
        ),
    )
    rule(
        "delete/gone",
        ["delete", "fetchMessage"],
        lambda t: t.post().flat_map(
            lambda posted: t.call(t.chat.delete(t.thread, posted.id)).and_then(
                t.expect_reason("NotFound", t.chat.fetch_message(t.thread, posted.id))
            )
        ),
    )
    rule(
        "delete/unknownId",
        ["delete"],
        lambda t: _gone_id(t).flat_map(
            lambda id: t.expect_reason("NotFound", t.chat.delete(t.thread, id))
        ),
    )

    def order(t: Tester) -> Effect[None, ConformanceFailure]:
        text = conformance_text(t.rule)

        @fx.gen
        def run() -> _Gen[None]:
            a: Posted = yield from t.post(markdown=text + " a")
            b: Posted = yield from t.post(markdown=text + " b")
            c: Posted = yield from t.post(markdown=text + " c")
            backward: list[ChatMessage] = yield from t.collect(
                t.chat.history(t.thread, direction="backward").take(3)
            )
            forward: list[ChatMessage] = yield from t.collect(
                t.chat.history(t.thread, direction="forward", from_=a.id).take(2)
            )
            yield from t.check(
                _ids(backward) == f"{c.id},{b.id},{a.id}",
                f"backward {c.id},{b.id},{a.id}",
                lambda: f"backward {_ids(backward)}",
            )
            yield from t.check(
                _ids(forward) == f"{b.id},{c.id}",
                f"forward {b.id},{c.id}",
                lambda: f"forward {_ids(forward)}",
            )

        return run

    rule("history/order", ["history"], order)

    def from_exclusive(t: Tester) -> Effect[None, ConformanceFailure]:
        text = conformance_text(t.rule)

        @fx.gen
        def run() -> _Gen[None]:
            a: Posted = yield from t.post(markdown=text + " a")
            b: Posted = yield from t.post(markdown=text + " b")
            before: list[ChatMessage] = yield from t.collect(
                t.chat.history(t.thread, direction="backward", from_=b.id).take(1)
            )
            after: list[ChatMessage] = yield from t.collect(
                t.chat.history(t.thread, direction="forward", from_=a.id).take(1)
            )
            first_before = before[0].id if before else None
            first_after = after[0].id if after else None
            yield from t.check(
                first_before == a.id and first_after == b.id,
                "the message next to from, not from itself",
                lambda: f"backward {first_before}, forward {first_after}",
            )

        return run

    rule("history/fromExclusive", ["history"], from_exclusive)

    def same_as_inbound(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            event: MessageCreated = yield from t.user_posts()
            history: list[ChatMessage] = yield from t.collect(
                t.chat.history(t.thread, direction="backward").take(20)
            )
            read = _find_in(history, event.message.id)
            yield from t.check(
                read is not None and same_message(event.message, read),
                "the inbound message in history",
                lambda: "no such message" if read is None else "a different message",
            )

        return run

    rule("history/sameAsInbound", ["history"], same_as_inbound)

    def starts_with_opener(t: Tester) -> Effect[None, ConformanceFailure]:
        text = conformance_text(t.rule)

        @fx.gen
        def run() -> _Gen[None]:
            opener: Posted = yield from t.post(markdown=text + " opener")
            thread: ChatThread = yield from t.call(
                t.chat.start_thread(t.thread, opener.id, name=text)
            )
            yield from t.post(markdown=text + " reply", thread=thread)
            first: list[ChatMessage] = yield from t.collect(
                t.chat.history(thread, direction="forward").take(1)
            )
            head = first[0] if first else None
            yield from t.check(
                head is not None
                and head.id == opener.id
                and chat_thread.equals(head.thread, t.thread),
                f"the opener first, addressed to {chat_thread.to_string(t.thread)}",
                lambda: (
                    "an empty history"
                    if head is None
                    else f"message {head.id} in {chat_thread.to_string(head.thread)}"
                ),
            )

        return run

    rule("history/startsWithOpener", ["history", "startThread"], starts_with_opener)

    def thread_stable(t: Tester) -> Effect[None, ConformanceFailure]:
        text = conformance_text(t.rule)

        @fx.gen
        def run() -> _Gen[None]:
            event: MessageCreated = yield from t.user_posts()
            id = event.message.id

            @fx.gen
            def read() -> _Gen[list[ChatMessage | None]]:
                fetched: ChatMessage = yield from t.call(t.chat.fetch_message(t.thread, id))
                history: list[ChatMessage] = yield from t.collect(
                    t.chat.history(t.thread, direction="backward").take(20)
                )
                return [fetched, _find_in(history, id)]

            before: list[ChatMessage | None] = yield from read
            thread: ChatThread = yield from t.call(t.chat.start_thread(t.thread, id, name=text))
            yield from t.post(markdown=text + " reply", thread=thread)
            after: list[ChatMessage | None] = yield from read
            reads = [event.message, *before, *after]
            yield from t.check(
                all(m is not None and chat_thread.equals(m.thread, t.thread) for m in reads),
                f"every read addressed to {chat_thread.to_string(t.thread)}",
                lambda: ", ".join(
                    "missing" if m is None else chat_thread.to_string(m.thread) for m in reads
                ),
            )

        return run

    rule("message/threadStable", ["fetchMessage", "history", "startThread"], thread_stable)

    def inbound_fetchable(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            event: MessageCreated = yield from t.user_posts()
            message: ChatMessage = yield from t.call(
                t.chat.fetch_message(event.thread, event.message.id)
            )
            yield from t.check(
                same_message(event.message, message),
                "the inbound message",
                lambda: "a different message",
            )

        return run

    rule("inbound/fetchable", ["fetchMessage"], inbound_fetchable)

    def not_self(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            event: MessageCreated = yield from t.user_posts()
            yield from t.check(
                not event.message.author.is_self,
                "author.is_self false",
                lambda: "author.is_self true",
            )
            yield from check_event(
                event, platform=t.options.platform, parse_mention=t.options.parse_mention
            ).map_error(lambda error: failure(t.rule, error.expected, error.actual, error.cause))

        return run

    rule("inbound/notSelf", [], not_self)

    def max_bytes(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post(files=(conformance_file(t.rule),))
            message: ChatMessage = yield from t.call(t.chat.fetch_message(t.thread, posted.id))
            yield from t.check(
                len(message.attachments) == 1,
                "one attachment",
                lambda: str(len(message.attachments)),
            )
            yield from t.expect_reason(
                "TooLarge",
                t.chat.download(t.thread, message.attachments[0], max_bytes=8).run_drain(),
            )

        return run

    rule("download/maxBytes", ["files", "download", "fetchMessage"], max_bytes)

    def idempotent(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post()
            first: ChatThread = yield from t.call(
                t.chat.start_thread(t.thread, posted.id, name=conformance_text(t.rule))
            )
            second: ChatThread = yield from t.call(t.chat.start_thread(t.thread, posted.id))
            yield from t.check(
                chat_thread.equals(first, second),
                chat_thread.to_string(first),
                lambda: chat_thread.to_string(second),
            )

        return run

    rule("startThread/idempotent", ["startThread"], idempotent)
    rule(
        "opener/noneOutsideThread",
        ["opener"],
        lambda t: t.call(t.chat.opener(t.thread)).flat_map(
            lambda opener: t.check(opener is None, "no opener", lambda: "an opener")
        ),
    )


def _stream_rules(rule: _AddRule, options: Options) -> None:
    def fits_message(t: Tester) -> Effect[None, ConformanceFailure]:
        limits = t.descriptor.limits
        return t.check(
            limits.stream_length is not None and limits.stream_length <= limits.message_length,
            f"limits.stream_length at most {limits.message_length}",
            lambda: f"limits.stream_length {limits.stream_length}",
        )

    rule("descriptor/streamFitsMessage", ["nativeStream"], fits_message)

    def open_stream(
        t: Tester, markdown: str
    ) -> Effect[tuple[NativeStream, Posted], ConformanceFailure, Registry]:
        @fx.gen
        def run() -> Generator[
            Effect[Any, ConformanceFailure, Registry], Any, tuple[NativeStream, Posted]
        ]:
            registry = yield from Registry()
            adapter = yield from t.call(registry.get(options.platform))
            native = adapter.native_stream
            assert native is not None
            event: MessageCreated = yield from t.user_posts()
            posted: Posted = yield from t.call(
                native.start(t.thread, markdown=markdown, recipient=event.message.author.id)
            )
            t.track(posted)
            return native, posted

        return run

    def concatenates(t: Tester) -> Effect[None, ConformanceFailure, Registry]:
        first = conformance_text(t.rule) + " one"

        @fx.gen
        def run() -> Generator[Effect[Any, ConformanceFailure, Registry], Any]:
            opened: tuple[NativeStream, Posted] = yield from open_stream(t, first)
            native, posted = opened
            appended: AppendResult = yield from t.call(
                native.append(t.thread, posted.id, " two", flush=True)
            ).ensuring(native.stop(t.thread, posted.id, end="done").ignore())
            yield from t.check(
                appended.state == "open" and appended.held == 0,
                "an open append holding nothing",
                lambda: f"{appended.state} holding {appended.held}",
            )
            message: ChatMessage = yield from t.call(t.chat.fetch_message(t.thread, posted.id))
            yield from t.check(
                message.text == first + " two",
                _json_text.quote(first + " two"),
                lambda: _json_text.quote(message.text),
            )

        return run

    rule("nativeStream/concatenates", ["nativeStream", "fetchMessage"], concatenates)

    def append_after_stop(t: Tester) -> Effect[None, ConformanceFailure, Registry]:
        first = conformance_text(t.rule)

        @fx.gen
        def run() -> Generator[Effect[Any, ConformanceFailure, Registry], Any]:
            opened: tuple[NativeStream, Posted] = yield from open_stream(t, first)
            native, posted = opened
            yield from t.call(native.stop(t.thread, posted.id, end="done"))
            appended: AppendResult = yield from t.call(
                native.append(t.thread, posted.id, " after", flush=True)
            )
            message: ChatMessage = yield from t.call(t.chat.fetch_message(t.thread, posted.id))
            yield from t.check(
                appended.state == "closed" and message.text == first,
                "closed, with the text unchanged",
                lambda: f"{appended.state} with {_json_text.quote(message.text)}",
            )

        return run

    rule("nativeStream/appendAfterStop", ["nativeStream", "fetchMessage"], append_after_stop)


type _LimitName = Literal[
    "actions_per_message", "action_data_length", "modal_metadata_length", "modal_fields"
]


def _limit(t: Tester, name: _LimitName) -> Effect[int, ConformanceFailure]:
    value: int | None = getattr(t.descriptor.limits, name)
    if value is None:
        return fx.fail(
            failure(
                t.rule, f"limits.{name} on a descriptor with its capability", f"no limits.{name}"
            )
        )
    return fx.succeed(value)


def _action_rules(rule: _AddRule) -> None:
    def posts(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post(actions=(conformance_button(t.rule),))
            if not t.has("fetchMessage"):
                return
            message: ChatMessage = yield from t.call(t.chat.fetch_message(t.thread, posted.id))
            yield from t.check(
                message.id == posted.id,
                f"the posted message {posted.id}",
                lambda: f"message {message.id}",
            )

        return run

    rule("actions/posts", ["buttons"], posts)

    def too_many(t: Tester) -> Effect[None, ConformanceFailure]:
        def post(most: int) -> Effect[None, ConformanceFailure]:
            actions = tuple(U.Button(id=f"c{i}", label=f"c{i}") for i in range(most + 1))
            return t.expect_reason(
                "TooLarge",
                t.chat.post(t.thread, markdown=conformance_text(t.rule), actions=actions),
                t.track,
            )

        return _limit(t, "actions_per_message").flat_map(post)

    rule("actions/tooMany", ["buttons"], too_many)

    def data_too_large(t: Tester) -> Effect[None, ConformanceFailure]:
        def post(most: int) -> Effect[None, ConformanceFailure]:
            id = "conformance" if most >= len("conformance") else "c" * (most + 1)
            value = "x" * (most + 1 - len(id))
            button = U.Button(id=id, label="c", value=value or None)
            return t.expect_reason(
                "TooLarge",
                t.chat.post(t.thread, markdown=conformance_text(t.rule), actions=(button,)),
                t.track,
            )

        return _limit(t, "action_data_length").flat_map(post)

    rule("actions/dataTooLarge", ["buttons"], data_too_large)

    def measure_adds_actions(t: Tester) -> Effect[None, ConformanceFailure]:
        measure = t.descriptor.measure
        button = conformance_button(t.rule)
        sets: list[tuple[U.Action, ...]] = [
            (button,),
            (U.Button(id=button.id, label=button.label, value="a < b & \U0001d400"),),
            (button, U.LinkButton(label="Link", url="https://example.com/?a=1&b=<2>")),
            (conformance_select(t.rule),),
        ]

        @fx.gen
        def run() -> _Gen[None]:
            for markdown in MEASURE_SAMPLES:
                yield from t.check(
                    measure(markdown, ()) == measure(markdown, ()),
                    "measure(md, ()) equal to measure(md)",
                    lambda md=markdown: f"{_json_text.quote(md)} measures {measure(md, ())}",
                )
                for actions in sets:
                    both = measure(markdown, actions)
                    yield from t.check(
                        measure(markdown, ())
                        <= both
                        <= measure(markdown, ()) + measure("", actions),
                        'measure(md) <= measure(md, actions) <= measure(md) + measure("", actions)',
                        lambda md=markdown, a=actions, n=both: (
                            f"{_json_text.quote(md)} with "
                            f"{','.join(type(x).__name__ for x in a)} measures {n}"
                        ),
                    )

        return run

    rule("descriptor/measureAddsActions", ["buttons"], measure_adds_actions)

    def measure_fits_actions(t: Tester) -> Effect[None, ConformanceFailure]:
        measure = t.descriptor.measure
        most = t.descriptor.limits.message_length
        # A short label, so a platform whose labels are short still takes the button.
        actions = (U.Button(id="conformance", label="fits", value="x"),)
        length = largest_fitting(most, lambda n: measure("x" * n, actions) <= most)
        return t.post(markdown="x" * length, actions=actions).as_(None)

    rule("descriptor/measureFitsActions", ["buttons"], measure_fits_actions)


def _click_rules(rule: _AddRule) -> None:  # noqa: PLR0915
    def value_round_trips(t: Tester) -> Effect[None, ConformanceFailure]:
        buttons = [
            ci.button(f"v{i}", label=f"v{i}", value=schema)
            for i, (schema, _) in enumerate(VALUE_CASES)
        ]

        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post(
                actions=tuple(b.of(VALUE_CASES[i][1]) for i, b in enumerate(buttons))
            )
            for i, (schema, value) in enumerate(VALUE_CASES):
                yield from t.click(posted.id, f"v{i}")
                click = t.recording.clicks[i] if i < len(t.recording.clicks) else None
                decoded = (
                    ci.decode_value(schema, click.value)
                    if isinstance(click, ci.ButtonClicked) and click.value is not None
                    else None
                )
                yield from t.check(
                    decoded is not None and same_value(schema, decoded.value, value),
                    f"a value that decodes to {canonical_json(_json_of(schema, value))}",
                    lambda c=click: (
                        "no click" if c is None else f"value {_json_text.quote(str(c.value))}"
                    ),
                )

        return run

    rule("actions/valueRoundTrips", ["buttons"], value_round_trips)

    def absent_value(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post(actions=(conformance_button(t.rule),))
            yield from t.click(posted.id, "conformance")
            click = t.recording.clicks[0] if t.recording.clicks else None
            yield from t.check(
                isinstance(click, ci.ButtonClicked) and click.value is None,
                "a click with no value",
                lambda: "no click" if click is None else f"value {click.value!r}",
            )

        return run

    rule("actions/absentValue", ["buttons"], absent_value)

    def origin(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post(actions=(conformance_button(t.rule),))
            yield from t.click(posted.id, "conformance")
            click = t.recording.clicks[0] if t.recording.clicks else None
            yield from t.check(
                click is not None
                and click.message_id == posted.id
                and chat_thread.equals(click.thread, posted.thread),
                f"a click on {posted.id} in {chat_thread.to_string(posted.thread)}",
                lambda: (
                    "no click"
                    if click is None
                    else f"{click.message_id} in {chat_thread.to_string(click.thread)}"
                ),
            )
            yield from t.check_interaction(click)

        return run

    rule("actions/origin", ["buttons"], origin)

    def select_value(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post(actions=(conformance_select(t.rule),))
            yield from t.click(posted.id, "conformance", "b")
            event = t.recording.clicks[0] if t.recording.clicks else None
            yield from t.check(
                isinstance(event, ci.SelectChanged) and event.value == "b",
                "SelectChanged with value b",
                lambda: (
                    "no click"
                    if event is None
                    else f"{type(event).__name__} with value {event.value!r}"
                ),
            )
            yield from t.check_interaction(event)

        return run

    rule("actions/selectValue", ["selects"], select_value)

    def removes_actions(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post(actions=(conformance_button(t.rule),))
            yield from t.call(
                t.chat.edit(t.thread, posted.id, markdown=conformance_text(t.rule) + " edited")
            )
            exit: Exit[None, Any] = yield from t.click_exit(posted.id, "conformance")
            error = error_of(exit)
            yield from t.check(
                isinstance(error, NoSuchElement),
                "NoSuchElement",
                lambda: describe_exit(exit),
            )

        return run

    rule("edit/removesActions", ["buttons", "edit"], removes_actions)

    def adds_actions(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.post()
            yield from t.call(
                t.chat.edit(
                    t.thread,
                    posted.id,
                    markdown=conformance_text(t.rule) + " edited",
                    actions=(conformance_button(t.rule),),
                )
            )
            yield from t.click(posted.id, "conformance")
            yield from t.check(
                len(t.recording.clicks) == 1,
                "one click",
                lambda: f"{len(t.recording.clicks)} clicks",
            )

        return run

    rule("edit/addsActions", ["buttons", "edit"], adds_actions)

    def modal_origin(t: Tester) -> Effect[None, ConformanceFailure]:
        @fx.gen
        def run() -> _Gen[None]:
            posted: Posted = yield from t.open_modal(PROBE_MODAL.open())
            yield from t.submit({"answer": "conformance"})
            submit = t.recording.submits[0] if t.recording.submits else None
            yield from t.check(
                submit is not None
                and submit.message_id == posted.id
                and chat_thread.equals(submit.thread, posted.thread),
                f"a submit from {posted.id} in {chat_thread.to_string(posted.thread)}",
                lambda: (
                    "no submit"
                    if submit is None
                    else f"{submit.message_id} in {chat_thread.to_string(submit.thread)}"
                ),
            )
            yield from t.check_interaction(submit)

        return run

    rule("modal/origin", ["modals"], modal_origin)

    def metadata_round_trips(t: Tester) -> Effect[None, ConformanceFailure]:
        with_metadata = ci.modal(
            "conformance-meta",
            title="Conformance",
            metadata=Version,
            fields={"answer": ci.text_input(label="Answer")},
        )
        value = Version(version="v1 < \U0001d400")

        @fx.gen
        def run() -> _Gen[None]:
            yield from t.open_modal(with_metadata.open(metadata=value))
            yield from t.submit({"answer": "conformance"})
            yield from t.open_modal(PROBE_MODAL.open())
            yield from t.submit({"answer": "conformance"})
            submits = t.recording.submits
            first = submits[0] if submits else None
            second = submits[1] if len(submits) > 1 else None
            decoded = (
                None
                if first is None or first.metadata is None
                else ci.decode_value(Version, first.metadata)
            )
            yield from t.check(
                decoded is not None and same_value(Version, decoded.value, value),
                f"metadata that decodes to {canonical_json(_json_of(Version, value))}",
                lambda: "no submit" if first is None else f"metadata {first.metadata!r}",
            )
            yield from t.check(
                second is not None and second.metadata is None,
                "a submit with no metadata",
                lambda: "no submit" if second is None else f"metadata {second.metadata!r}",
            )

        return run

    rule("modal/metadataRoundTrips", ["modals"], metadata_round_trips)

    def refused_too_large(t: Tester) -> Effect[None, ConformanceFailure]:
        def check() -> Effect[None, ConformanceFailure]:
            refusal = t.recording.refused[0] if t.recording.refused else None
            submitted = len(t.recording.submits)
            return t.check(
                refusal is not None and refusal.reason._tag == "TooLarge" and submitted == 0,  # pyright: ignore[reportPrivateUsage]
                "a refusal TooLarge and no modal",
                lambda: (
                    ("no refusal" if refusal is None else f"a refusal {describe_error(refusal)}")
                    + ("" if submitted == 0 else " and a submit")
                ),
            )

        return t.submit({}).and_then(fx.suspend(check))

    def metadata_too_large(t: Tester) -> Effect[None, ConformanceFailure]:
        id = "conformance-big"
        big = ci.modal(
            id,
            title="Conformance",
            metadata=S.String,
            fields={"answer": ci.text_input(label="Answer")},
        )
        return (
            _limit(t, "modal_metadata_length")
            .flat_map(
                lambda most: t.open_modal(big.open(metadata="x" * max(0, most + 1 - len(id))))
            )
            .and_then(refused_too_large(t))
        )

    rule("modal/metadataTooLarge", ["modals"], metadata_too_large)

    def too_many_fields(t: Tester) -> Effect[None, ConformanceFailure]:
        def open_many(most: int) -> Effect[Posted, ConformanceFailure]:
            fields = {f"f{i}": ci.text_input(label=f"F{i}") for i in range(most + 1)}
            return t.open_modal(
                ci.modal("conformance-many", title="Conformance", fields=fields).open()
            )

        return _limit(t, "modal_fields").flat_map(open_many).and_then(refused_too_large(t))

    rule("modal/tooManyFields", ["modals"], too_many_fields)

    # ``modalErrors`` means nothing without ``modals``, so the rule needs both.
    def errors_keep_open(t: Tester) -> Effect[None, ConformanceFailure]:
        t.recording.on_submit = lambda _: (
            ci.errors(answer="Again.") if len(t.recording.submits) == 1 else ci.close
        )

        @fx.gen
        def run() -> _Gen[None]:
            yield from t.open_modal(PROBE_MODAL.open())
            yield from t.submit({"answer": "first"})
            yield from t.submit({"answer": "second"})
            second = t.recording.submits[1] if len(t.recording.submits) > 1 else None
            yield from t.check(
                second is not None and second.id == "conformance-modal",
                "a second submit of the same modal",
                lambda: f"{len(t.recording.submits)} submits",
            )

        return run

    rule("modal/errorsKeepOpen", ["modals", "modalErrors"], errors_keep_open)
    rule("unsupported/modals", ["buttons"], lambda t: t.probe("modals"))


def _json_of(schema: Any, value: object) -> object:
    return S.encode_sync(S.to_codec_json(schema))(value)


def _command_rules(rule: _AddRule) -> None:
    command_id = "conformance-command"

    def arrives(t: Tester) -> Effect[None, ConformanceFailure]:
        text = "deploy v1 < \U0001d400"

        @fx.gen
        def run() -> _Gen[None]:
            yield from t.command(command_id, text)
            command = t.recording.commands[0] if t.recording.commands else None
            yield from t.check(
                command is not None
                and command.id == command_id
                and command.text == text
                and chat_thread.equals(command.thread, t.thread),
                f"command {command_id} with text {_json_text.quote(text)} in "
                f"{chat_thread.to_string(t.thread)}",
                lambda: (
                    "no command"
                    if command is None
                    else f"command {command.id} with text {_json_text.quote(command.text)} in "
                    f"{chat_thread.to_string(command.thread)}"
                ),
            )
            yield from t.check_interaction(command)

        return run

    rule("command/arrives", ["commands"], arrives)

    def empty_text(t: Tester) -> Effect[None, ConformanceFailure]:
        def check() -> Effect[None, ConformanceFailure]:
            command = t.recording.commands[0] if t.recording.commands else None
            return t.check(
                command is not None and command.text == "",
                'a command with text ""',
                lambda: (
                    "no command" if command is None else f"text {_json_text.quote(command.text)}"
                ),
            )

        return t.command(command_id).and_then(fx.suspend(check))

    rule("command/emptyText", ["commands"], empty_text)

    def no_refusal(t: Tester) -> Effect[None, ConformanceFailure]:
        def check() -> Effect[None, ConformanceFailure]:
            commands, refused = t.recording.commands, t.recording.refused
            return t.check(
                len(commands) == 1 and len(refused) == 0,
                "one command and no refusal",
                lambda: (
                    f"{len(commands)} commands and refusals "
                    + (", ".join(describe_error(e) for e in refused) or "none")
                ),
            )

        return fx.suspend(check)

    def responds(t: Tester) -> Effect[None, ConformanceFailure]:
        t.recording.on_command = lambda _: ci.respond(
            markdown=conformance_text(t.rule), visibility="public"
        )
        return t.command(command_id).and_then(no_refusal(t))

    rule("command/responds", ["commands"], responds)

    def responds_privately(t: Tester) -> Effect[None, ConformanceFailure]:
        t.recording.on_command = lambda _: ci.respond(markdown=conformance_text(t.rule))
        return t.command(command_id).and_then(no_refusal(t))

    rule("command/respondsPrivately", ["commands", "ephemeral"], responds_privately)

    def respond_too_large(t: Tester) -> Effect[None, ConformanceFailure]:
        markdown = "x" * (t.descriptor.limits.message_length + 1)
        t.recording.on_command = lambda _: ci.respond(markdown=markdown, visibility="public")

        def check() -> Effect[None, ConformanceFailure]:
            refusal = t.recording.refused[0] if t.recording.refused else None
            return t.check(
                refusal is not None and TEXT_TOO_LARGE.test(refusal.reason),
                f"a refusal {TEXT_TOO_LARGE.expected}",
                lambda: "no refusal" if refusal is None else f"a refusal {describe_error(refusal)}",
            )

        return t.command(command_id).and_then(fx.suspend(check))

    rule("command/respondTooLarge", ["commands"], respond_too_large)

    def follow_up(t: Tester) -> Effect[None, ConformanceFailure]:
        t.recording.on_command = lambda command: ci.defer(command, visibility="public")

        @fx.gen
        def run() -> _Gen[None]:
            yield from t.command(command_id)
            replies = t.recording.command_replies
            deferred = replies[0] if replies else None
            if not isinstance(deferred, ci.Defer):
                yield from fx.fail(
                    failure(
                        t.rule,
                        "a Defer reply",
                        "no command" if deferred is None else deferred._tag,  # pyright: ignore[reportPrivateUsage]
                    )
                )
                return
            yield from no_refusal(t)
            yield from t.call(t.chat.follow_up(deferred, markdown=conformance_text(t.rule)))

        return run

    rule("command/followUp", ["commands"], follow_up)

    def modal_origin(t: Tester) -> Effect[None, ConformanceFailure]:
        t.recording.on_command = lambda _: PROBE_MODAL.open()

        @fx.gen
        def run() -> _Gen[None]:
            yield from t.command(command_id)
            yield from t.submit({"answer": "conformance"})
            submit = t.recording.submits[0] if t.recording.submits else None
            yield from t.check(
                submit is not None
                and submit.message_id is None
                and chat_thread.equals(submit.thread, t.thread),
                f"a submit in {chat_thread.to_string(t.thread)} with no message_id",
                lambda: (
                    "no submit"
                    if submit is None
                    else f"a submit in {chat_thread.to_string(submit.thread)} "
                    f"with message_id {submit.message_id}"
                ),
            )
            yield from t.check_interaction(submit)

        return run

    rule("command/modalOrigin", ["commands", "modals"], modal_origin)
    rule("unsupported/ephemeral", ["commands"], lambda t: t.probe("ephemeral"))


def _retry_rules(rule: _AddRule, fail_next: Callable[[str, AnyReason], Effect[None]]) -> None:
    rule(
        "retries/noneWithoutRetries",
        [],
        lambda t: fail_next("post", RateLimited()).and_then(
            t.expect_reason(
                "RateLimited",
                _chat.without_retries(t.chat.post(t.thread, markdown=conformance_text(t.rule))),
                t.track,
            )
        ),
    )

    def retry_safe(t: Tester) -> Effect[None, ConformanceFailure]:
        retry_after = millis(100)

        @fx.gen
        def run() -> _Gen[None]:
            yield from fail_next("post", RateLimited(retry_after=retry_after))
            start = yield from _date_time.now()
            yield from t.post()
            elapsed = (yield from _date_time.now()) - start
            elapsed_ms = elapsed.total_seconds() * 1000
            yield from t.check(
                # One millisecond of slack: a timer and the clock round to whole milliseconds apart.
                elapsed_ms + 1 >= retry_after.to_millis(),
                f"a retry after {retry_after.format()}",
                lambda: f"a retry after {elapsed_ms:g} millis",
            )

        return run

    rule("retries/retrySafe", [], retry_safe)
    rule(
        "retries/neverUncertain",
        [],
        lambda t: fail_next("post", Transport(retry="uncertain")).and_then(
            t.expect_reason(
                "Transport", t.chat.post(t.thread, markdown=conformance_text(t.rule)), t.track
            )
        ),
    )


__all__ = ["Rule", "conformance"]
