"""The invariants every adapter's reads hold, and the conformance suite
every adapter must pass; ``chat_test`` re-exports them."""

from __future__ import annotations

import re
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Never

import pyfect as fx
from pyfect import _json_text
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.chat import chat as _chat
from pyfect.chat import chat_event as _event
from pyfect.chat import chat_interaction as ci
from pyfect.chat import chat_thread
from pyfect.chat import chat_ui as U
from pyfect.chat.chat_adapter import Descriptor, File, Posted, Registry
from pyfect.chat.chat_error import (
    FILE_REFUSED,
    AnyReason,
    Capability,
    ChatError,
    ChatErrorReason,
    TooLarge,
    Unsupported,
)
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.chat.chat_message import (
    Attachment,
    ChatMessage,
    Mention,
    MentionKind,
    ReplyTo,
    utf16_length,
    utf16_slice,
)
from pyfect.chat.chat_test import ConformanceFailure, NoSuchElement
from pyfect.chat.chat_thread import ChatThread
from pyfect.exit import Exit, Success
from pyfect.result import Ok
from pyfect.schema._error import SchemaError
from pyfect.schema._exact import Exact, as_codec
from pyfect.stream import Stream


@dataclass(frozen=True)
class MentionToken:
    """What a ``ParseMention`` reads from a mention's slice of text."""

    kind: MentionKind
    id: str


type ParseMention = Callable[[str], MentionToken | None]
"""Parses one mention token, as the platform writes it, into its kind and
id; ``None`` when the slice is not a token."""


# --- invariants ----------------------------------------------------------------------


def _same_mentions(a: Sequence[Mention], b: Sequence[Mention]) -> bool:
    return len(a) == len(b) and all(
        x.kind == y.kind
        and x.id == y.id
        and x.start == y.start
        and x.end == y.end
        and x.is_self == y.is_self
        for x, y in zip(a, b, strict=True)
    )


def _same_reply_to(a: ReplyTo | None, b: ReplyTo | None) -> bool:
    if a is None or b is None:
        return a is b
    return a.message_id == b.message_id and a.author_id == b.author_id and a.is_self == b.is_self


def same_message(a: ChatMessage, b: ChatMessage) -> bool:
    """Whether two reads of a message are the same message: ``id``,
    ``thread``, ``author.id``/``is_bot``/``is_self``, ``text``,
    ``mentions``, ``reply_to``, ``timestamp`` and the attachment ids in
    order. ``raw``, ``author.name`` and the optional attachment fields are
    left out."""
    return (
        a.id == b.id
        and chat_thread.equals(a.thread, b.thread)
        and a.author.id == b.author.id
        and a.author.is_bot == b.author.is_bot
        and a.author.is_self == b.author.is_self
        and a.text == b.text
        and _same_mentions(a.mentions, b.mentions)
        and _same_reply_to(a.reply_to, b.reply_to)
        and a.timestamp == b.timestamp
        and [x.id for x in a.attachments] == [y.id for y in b.attachments]
    )


def canonical_json(value: object) -> str:
    return _json_text.stringify(value, sort_keys=True)


def failure(rule: str, expected: str, actual: str, cause: object = None) -> ConformanceFailure:
    return ConformanceFailure(rule=rule, expected=expected, actual=actual, cause=cause)


def check(
    rule: str, condition: bool, expected: str, actual: Callable[[], str]
) -> Effect[None, ConformanceFailure]:
    return fx.void if condition else fx.fail(failure(rule, expected, actual()))


_MESSAGE_JSON = S.to_codec_json(ChatMessage)
_EVENT_JSON = S.to_codec_json(_event.CHAT_EVENT)
_INTERACTION_JSON = S.to_codec_json(ci.INTERACTION)


def _round_trip[T](
    rule: str, schema: Exact[T, Never, Never], value: T
) -> Effect[T, ConformanceFailure]:
    codec = as_codec(schema)
    encode = S.encode_effect(codec)
    decode = S.decode_effect(codec)

    @fx.gen
    def run() -> Generator[Effect[Any, SchemaError | ConformanceFailure], Any, T]:
        encoded: object = yield from encode(value)
        decoded: T = yield from decode(encoded)
        again: object = yield from encode(decoded)
        yield from check(
            rule,
            canonical_json(encoded) == canonical_json(again),
            "an unchanged value after encoding and decoding",
            lambda: canonical_json(again),
        )
        return decoded

    def to_failure(error: SchemaError) -> Effect[Never, ConformanceFailure]:
        return fx.fail(failure(rule, "a value that encodes and decodes", "SchemaError", error))

    return run.catch_if(lambda e: isinstance(e, SchemaError), to_failure)  # pyright: ignore[reportArgumentType, reportReturnType]


def _check_thread(rule: str, thread: ChatThread, platform: str) -> Effect[None, ConformanceFailure]:
    decoded = chat_thread.from_string(chat_thread.to_string(thread))
    return check(
        rule,
        thread.platform == platform,
        f"platform {platform}",
        lambda: f"platform {thread.platform}",
    ).and_then(
        check(
            rule,
            decoded is not None and chat_thread.equals(decoded, thread),
            "a thread that survives its string codec",
            lambda: chat_thread.to_string(thread),
        )
    )


_URL = re.compile(r"^[a-z]+://", re.IGNORECASE)


def _check_message_with(
    rule: str, message: ChatMessage, platform: str, parse_mention: ParseMention
) -> Effect[None, ConformanceFailure]:
    @fx.gen
    def run() -> Generator[Effect[Any, ConformanceFailure], Any]:
        yield from _check_thread(rule, message.thread, platform)
        end = 0
        length = utf16_length(message.text)
        for mention in sorted(message.mentions, key=lambda m: m.start):
            yield from check(
                rule,
                mention.start >= end and mention.start < mention.end and mention.end <= length,
                "mentions inside text without overlap",
                lambda m=mention: f"mention at {m.start}-{m.end}",
            )
            end = mention.end
            parsed = parse_mention(utf16_slice(message.text, mention.start, mention.end))
            yield from check(
                rule,
                parsed is not None and parsed.kind == mention.kind and parsed.id == mention.id,
                f"a {mention.kind} mention token at {mention.start}-{mention.end}",
                lambda p=parsed: "no mention token" if p is None else f"a {p.kind} token",
            )
        for attachment in message.attachments:
            yield from check(
                rule,
                len(attachment.id) > 0
                and not hasattr(attachment, "url")
                and _URL.match(attachment.id) is None,
                "an attachment with an id and no URL",
                lambda a=attachment: "attachment " + ("with a URL" if a.id else "without an id"),
            )
        if message.reply_to is not None:
            author_id, is_self = message.reply_to.author_id, message.reply_to.is_self
            yield from check(
                rule,
                (author_id is None) == (is_self is None),
                "reply_to.is_self set exactly when reply_to.author_id is",
                lambda: f"author_id {author_id}, is_self {is_self}",
            )
        decoded: ChatMessage = yield from _round_trip(rule, _MESSAGE_JSON, message)
        yield from check(
            rule,
            same_message(message, decoded),
            "the same message after decoding",
            lambda: "a different message",
        )

    return run


def check_message(
    message: ChatMessage, *, platform: str, parse_mention: ParseMention
) -> Effect[None, ConformanceFailure]:
    """Checks the invariants every message holds, for fixture tests and live
    runs: every mention sits inside ``text`` without overlap and its slice
    parses with ``parse_mention`` as its kind and id; ``thread.platform`` is
    the platform and the thread survives its string codec; the message
    encodes and decodes through its schema unchanged, ``raw`` included;
    every attachment has an id and no URL; ``reply_to.is_self`` is set
    exactly when ``reply_to.author_id`` is."""
    return _check_message_with("checkMessage", message, platform, parse_mention)


def check_event(
    event: ChatEvent, *, platform: str, parse_mention: ParseMention
) -> Effect[None, ConformanceFailure]:
    """Checks the invariants every event holds: a message event's message
    passes ``check_message`` and shares the event's thread; the thread is
    the platform's and survives its string codec; the event round-trips
    through its schema with the same ``dedupe_key`` every decode; a
    reaction's key differs between added and removed."""
    rule = "checkEvent"

    @fx.gen
    def run() -> Generator[Effect[Any, ConformanceFailure], Any]:
        yield from _check_thread(rule, event.thread, platform)
        if isinstance(event, MessageCreated):
            yield from _check_message_with(rule, event.message, platform, parse_mention)
            yield from check(
                rule,
                chat_thread.equals(event.thread, event.message.thread),
                "the event's thread equal to the message's",
                lambda: chat_thread.to_string(event.thread),
            )
        elif isinstance(event, (_event.ReactionAdded, _event.ReactionRemoved)):
            flipped: ChatEvent = (
                _event.ReactionRemoved
                if isinstance(event, _event.ReactionAdded)
                else _event.ReactionAdded
            )(
                thread=event.thread,
                message_id=event.message_id,
                message_author_id=event.message_author_id,
                user_id=event.user_id,
                emoji=event.emoji,
                timestamp=event.timestamp,
                raw=event.raw,
            )
            yield from check(
                rule,
                _event.dedupe_key(flipped) != _event.dedupe_key(event),
                "different keys for an added and a removed reaction",
                lambda: _event.dedupe_key(event),
            )
        first: ChatEvent = yield from _round_trip(rule, _EVENT_JSON, event)
        second: ChatEvent = yield from _round_trip(rule, _EVENT_JSON, event)
        key = _event.dedupe_key(event)
        yield from check(
            rule,
            _event.dedupe_key(first) == key and _event.dedupe_key(second) == key,
            "the same dedupe_key for every decode",
            lambda: f"{_event.dedupe_key(first)} and {_event.dedupe_key(second)}",
        )

    return run


def check_interaction(
    interaction: ci.Interaction, *, platform: str
) -> Effect[None, ConformanceFailure]:
    """Checks the invariants every interaction holds: the thread is the
    platform's and survives its string codec; the interaction round-trips
    through its schema, ``raw`` included; a ``ModalSubmitted``'s
    ``message_id`` is non-empty when there (a command's modal has none); a
    ``CommandInvoked`` has a non-empty ``id``."""
    rule = "checkInteraction"
    checks = _check_thread(rule, interaction.thread, platform)
    if isinstance(interaction, ci.ModalSubmitted):
        checks = checks.and_then(
            check(
                rule,
                interaction.message_id != "",
                "a submit with no message_id or a non-empty one",
                lambda: "an empty message_id",
            )
        )
    if isinstance(interaction, ci.CommandInvoked):
        checks = checks.and_then(
            check(
                rule, interaction.id != "", "a command with a non-empty id", lambda: "an empty id"
            )
        )
    return checks.and_then(_round_trip(rule, _INTERACTION_JSON, interaction)).as_(None)


# --- conformance ---------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Interactions:
    """The click hook of ``conformance``: a way to click, for the adapter
    under test.

    - ``click(message_id, id, option)`` clicks an element of a message the
      suite posted through the adapter's real entry, failing
      ``NoSuchElement`` when the message has no such element.
    - ``submit(values)`` submits the modal the last click or command
      opened, and again after an ``errors`` reply; it does nothing when no
      modal is open.
    - ``command(thread, id, text)`` sends a command typed at ``thread``;
      the command rules exist only when it is given.
    - All three need ``chat_interaction.Handler`` and nothing else: the
      suite provides its own recording handler at the call.
    """

    click: Callable[[str, str, str | None], Effect[None, NoSuchElement, ci.Handler]]
    submit: Callable[[Mapping[str, str]], Effect[None, Never, ci.Handler]]
    command: Callable[[ChatThread, str, str], Effect[None, Never, ci.Handler]] | None = None


type Click = ci.ButtonClicked | ci.SelectChanged


def conformance_text(rule: str) -> str:
    return f"conformance {rule}"


@dataclass(eq=False)
class Recording:
    """What the suite's own handler received, and how it answers."""

    clicks: list[Click] = field(default_factory=lambda: [])
    submits: list[ci.ModalSubmitted] = field(default_factory=lambda: [])
    commands: list[ci.CommandInvoked] = field(default_factory=lambda: [])
    command_replies: list[ci.CommandReply] = field(default_factory=lambda: [])
    refused: list[ChatError] = field(default_factory=lambda: [])
    on_click: Callable[[Click], ci.ClickReply] = lambda _: ci.ack
    on_submit: Callable[[ci.ModalSubmitted], ci.SubmitReply] = lambda _: ci.close
    on_command: Callable[[ci.CommandInvoked], ci.CommandReply] = lambda event: ci.respond(
        markdown=conformance_text(event.id), visibility="public"
    )

    def handler(self) -> ci.HandlerService:
        def click(event: Click) -> Effect[ci.ClickReply]:
            def run() -> ci.ClickReply:
                self.clicks.append(event)
                return self.on_click(event)

            return fx.sync(run)

        def submit(event: ci.ModalSubmitted) -> Effect[ci.SubmitReply]:
            def run() -> ci.SubmitReply:
                self.submits.append(event)
                return self.on_submit(event)

            return fx.sync(run)

        def command(event: ci.CommandInvoked) -> Effect[ci.CommandReply]:
            def run() -> ci.CommandReply:
                self.commands.append(event)
                reply = self.on_command(event)
                self.command_replies.append(reply)
                return reply

            return fx.sync(run)

        def refused(_: Click | ci.CommandInvoked, error: ChatError) -> Effect[None]:
            return fx.sync(lambda: self.refused.append(error))

        return ci.HandlerService(click=click, submit=submit, command=command, refused=refused)


def conformance_button(rule: str) -> U.Button:
    return U.Button(id="conformance", label=rule)


def conformance_select(rule: str) -> U.Select:
    return U.Select(
        id="conformance",
        placeholder=rule,
        options=(U.SelectOption(label="a", value="a"), U.SelectOption(label="b", value="b")),
    )


def conformance_file(rule: str) -> File:
    return File(
        "conformance.txt", "text/plain", text_encode(conformance_text(rule) + " " + "x" * 64)
    )


def first_missing(needs: Sequence[Capability], have: frozenset[Capability]) -> Capability | None:
    """The first of ``needs`` not in ``have``."""
    for capability in needs:
        if capability not in have:
            return capability
    return None


def error_of[E](exit: Exit[Any, E]) -> E | None:
    found = exit.find_error()
    return found.value if isinstance(found, Ok) else None


def describe_error(error: object) -> str:
    if not isinstance(error, ChatError):
        return str(error)
    reason = error.reason
    return (
        f"Unsupported({reason.capability})" if isinstance(reason, Unsupported) else reason._tag  # pyright: ignore[reportPrivateUsage]
    )


def describe_exit(exit: Exit[Any, Any]) -> str:
    if isinstance(exit, Success):
        return "success"
    error = error_of(exit)
    return "a defect or interruption" if error is None else describe_error(error)


def reason_tag(reason: ChatErrorReason) -> str:
    return reason._tag  # pyright: ignore[reportPrivateUsage]


@dataclass(frozen=True)
class Refine:
    expected: str
    test: Callable[[ChatErrorReason], bool]


# A refusal of the text must not blame the files, or chat_markdown would post again without them.
TEXT_TOO_LARGE = Refine(
    "TooLarge without subject files or detail file_refused",
    lambda reason: (
        isinstance(reason, TooLarge) and reason.subject != "files" and reason.detail != FILE_REFUSED
    ),
)

MENTION_LIKE = "@everyone @here <@U0000> <!here> <!channel> <@&1> <#C0000>"

# Text a platform takes in any quantity: no emoji, which Slack limits separately.
MEASURE_FITS_BLOCK = "a < b & c > d\n\n```ts\nconst x = 1 < 2\n```\n\n\U0001d400\U0001d401 café\n\n"

MEASURE_SAMPLES: tuple[str, ...] = (
    "",
    "x",
    "hello world",
    "<",
    "a < b",
    "<@U0000>",
    "&amp; > &",
    "```\ncode < 1\n```\n",
    "```",
    "\U0001d400\U0001d401",
    "\U0001f600\U0001f44d\U0001f3fd",
    ":grinning:",
    "café",
)

PROBE_MODAL = ci.modal(
    "conformance-modal",
    title="Conformance",
    fields={"answer": ci.text_input(label="Answer")},
)


class VersionAttempt(S.Class):
    version: str
    attempt: float


class Version(S.Class):
    version: str


# The fixed schemas of ``actions/valueRoundTrips``, each with the value posted.
VALUE_CASES: tuple[tuple[ci.ValueSchema[Any], object], ...] = (
    (S.String, "v1.4.2"),
    (VersionAttempt, VersionAttempt(version="v1", attempt=2)),
    (S.Union(S.String, S.Number), 123),
    (S.Union(S.String, S.Number), "123"),
    (S.String, 'a < b & "c" \U0001d400'),
)


def same_value(schema: ci.ValueSchema[Any], a: object, b: object) -> bool:
    encode = S.encode_sync(S.to_codec_json(schema))
    return type(a) is type(b) and canonical_json(encode(a)) == canonical_json(encode(b))


def largest_fitting(limit: int, fits: Callable[[int], bool]) -> int:
    """The largest ``n`` in ``[0, limit]`` that ``fits``, for a ``fits`` that
    holds up to some ``n`` and fails past it."""
    low, high = 0, limit
    while low < high:
        middle = (low + high + 1) // 2
        if fits(middle):
            low = middle
        else:
            high = middle - 1
    return low


@dataclass(frozen=True, kw_only=True)
class Options:
    platform: str
    thread: ChatThread
    user_posts: Callable[[ChatThread, str], Effect[ChatEvent]]
    parse_mention: ParseMention
    refuse_files: Callable[[], Effect[None]] | None
    interactions: Interactions | None
    fail_next: Callable[[str, AnyReason], Effect[None]] | None


@dataclass(frozen=True)
class Created:
    thread: ChatThread
    id: str


class Tester:
    def __init__(
        self, rule: str, chat: _chat.Service, descriptor: Descriptor, options: Options
    ) -> None:
        self.rule = rule
        self.chat = chat
        self.descriptor = descriptor
        self.options = options
        self.created: list[Created] = []
        self.recording = Recording()

    @property
    def thread(self) -> ChatThread:
        return self.options.thread

    @property
    def interactions(self) -> Interactions:
        assert self.options.interactions is not None
        return self.options.interactions

    def recorded[A, E](self, effect: Effect[A, E, ci.Handler]) -> Effect[A, E]:
        return effect.pipe(fx.provide_service(ci.Handler, self.recording.handler()))

    def click_exit(
        self, message_id: str, id: str, option: str | None = None
    ) -> Effect[Exit[None, NoSuchElement]]:
        return self.recorded(self.interactions.click(message_id, id, option)).exit()

    def click(
        self, message_id: str, id: str, option: str | None = None
    ) -> Effect[None, ConformanceFailure]:
        def judge(exit: Exit[None, NoSuchElement]) -> Effect[None, ConformanceFailure]:
            if isinstance(exit, Success):
                return fx.void
            return fx.fail(
                failure(
                    self.rule,
                    f"a click on element {id} of message {message_id}",
                    describe_exit(exit),
                    error_of(exit),
                )
            )

        return self.click_exit(message_id, id, option).flat_map(judge)

    def command(self, id: str, text: str = "") -> Effect[None]:
        command = self.interactions.command
        assert command is not None
        return self.recorded(command(self.thread, id, text))

    def submit(self, values: Mapping[str, str]) -> Effect[None]:
        interactions = self.interactions
        return self.recorded(interactions.submit(values))

    def check_interaction(
        self, interaction: ci.Interaction | None
    ) -> Effect[None, ConformanceFailure]:
        if interaction is None:
            return fx.void
        return check_interaction(interaction, platform=self.options.platform).map_error(
            lambda error: failure(self.rule, error.expected, error.actual, error.cause)
        )

    def has(self, capability: Capability) -> bool:
        return capability in self.descriptor.capabilities

    def open_modal(self, modal: ci.OpenModal) -> Effect[Posted, ConformanceFailure]:
        """A click whose handler answers with ``modal``."""
        # A modal opens from a click, on a select when there are no buttons.
        element: U.Action = (
            conformance_button(self.rule)
            if self.has("buttons") or not self.has("selects")
            else conformance_select(self.rule)
        )

        def opened(posted: Posted) -> Effect[Posted, ConformanceFailure]:
            self.recording.on_click = lambda _: modal
            return self.click(posted.id, "conformance").as_(posted)

        return self.post(actions=(element,)).flat_map(opened)

    def call[A](self, effect: Effect[A, ChatError]) -> Effect[A, ConformanceFailure]:
        def to_failure(error: ChatError) -> ConformanceFailure:
            reason = error.reason
            listed = isinstance(reason, Unsupported) and self.has(reason.capability)
            return failure(
                self.rule,
                "success",
                describe_error(error) + (" for a listed capability" if listed else ""),
                error,
            )

        return effect.map_error(to_failure)

    def collect[A](self, stream: Stream[A, ChatError]) -> Effect[list[A], ConformanceFailure]:
        return self.call(stream.run_collect()).map(list)

    def check(
        self, condition: bool, expected: str, actual: Callable[[], str]
    ) -> Effect[None, ConformanceFailure]:
        return check(self.rule, condition, expected, actual)

    def track(self, posted: Posted) -> None:
        self.created.append(Created(self.thread, posted.id))

    def post(
        self,
        *,
        markdown: str | None = None,
        reply_to: ReplyTo | None = None,
        files: Sequence[File] = (),
        actions: Sequence[U.Action] = (),
        thread: ChatThread | None = None,
    ) -> Effect[Posted, ConformanceFailure]:
        target = self.thread if thread is None else thread

        def remember(posted: Posted) -> None:
            self.created.append(Created(target, posted.id))

        return self.call(
            self.chat.post(
                target,
                markdown=conformance_text(self.rule) if markdown is None else markdown,
                reply_to=reply_to,
                files=files,
                actions=actions,
            )
        ).tap(lambda posted: fx.sync(lambda: remember(posted)))

    def user_posts(self) -> Effect[MessageCreated, ConformanceFailure]:
        def narrow(event: ChatEvent) -> Effect[MessageCreated, ConformanceFailure]:
            if isinstance(event, MessageCreated):
                return fx.succeed(event)
            return fx.fail(
                failure(
                    self.rule,
                    "a MessageCreated event from user_posts",
                    event._tag,  # pyright: ignore[reportPrivateUsage]
                )
            )

        return self.options.user_posts(self.thread, conformance_text(self.rule)).flat_map(narrow)

    def expect_reason[A](
        self,
        tag: str,
        effect: Effect[A, ChatError],
        on_success: Callable[[A], None] | None = None,
        refine: Refine | None = None,
    ) -> Effect[None, ConformanceFailure]:
        def judge(exit: Exit[A, ChatError]) -> Effect[None, ConformanceFailure]:
            if isinstance(exit, Success) and on_success is not None:
                on_success(exit.value)
            error = error_of(exit)
            matches = (
                isinstance(error, ChatError)
                and reason_tag(error.reason) == tag
                and (refine is None or refine.test(error.reason))
            )
            if matches:
                return fx.void
            return fx.fail(
                failure(
                    self.rule,
                    tag if refine is None else refine.expected,
                    describe_exit(exit),
                    error,
                )
            )

        return effect.exit().flat_map(judge)

    def _expect_probe[A](
        self,
        capability: Capability,
        effect: Effect[A, ChatError],
        on_success: Callable[[A], None] | None = None,
    ) -> Effect[None, ConformanceFailure]:
        listed = self.has(capability)
        expected = (
            f"no Unsupported for listed {capability}" if listed else f"Unsupported({capability})"
        )

        def judge(exit: Exit[A, ChatError]) -> Effect[None, ConformanceFailure]:
            if isinstance(exit, Success) and on_success is not None:
                on_success(exit.value)
            error = error_of(exit)
            reason = error.reason if isinstance(error, ChatError) else None
            holds = (
                isinstance(exit, Success)
                or (reason is not None and not isinstance(reason, Unsupported))
                if listed
                else isinstance(reason, Unsupported) and reason.capability == capability
            )
            if holds:
                return fx.void
            return fx.fail(failure(self.rule, expected, describe_exit(exit), error))

        return effect.exit().flat_map(judge)

    def _check_refusal(self, capability: Capability) -> Effect[None, ConformanceFailure]:
        """Whether the handler was refused ``Unsupported`` exactly when the
        capability is not listed."""
        listed = self.has(capability)

        def check() -> Effect[None, ConformanceFailure]:
            refused = self.recording.refused
            refusal = next((e for e in refused if isinstance(e.reason, Unsupported)), None)
            holds = (
                refusal is None
                if listed
                else refusal is not None
                and isinstance(refusal.reason, Unsupported)
                and refusal.reason.capability == capability
            )
            return self.check(
                holds,
                f"no refusal Unsupported for listed {capability}"
                if listed
                else f"a refusal Unsupported({capability})",
                lambda: ", ".join(describe_error(e) for e in refused) or "no refusal",
            )

        return fx.suspend(check)

    def probe(self, capability: Capability) -> Effect[None, ConformanceFailure, Registry]:  # noqa: PLR0911, PLR0912
        """Calls the op behind ``capability``. Without it the op must fail
        ``Unsupported`` naming it; with it the op must not fail
        ``Unsupported`` at all, so a descriptor that lies either way fails."""
        chat, thread = self.chat, self.thread
        text = conformance_text(self.rule)

        def expect[A](
            effect: Effect[A, ChatError], on_success: Callable[[A], None] | None = None
        ) -> Effect[None, ConformanceFailure]:
            return self._expect_probe(capability, effect, on_success)

        def after_post[A](
            f: Callable[[Posted], Effect[A, ChatError]],
        ) -> Effect[None, ConformanceFailure]:
            return self.post().flat_map(lambda posted: expect(f(posted)))

        match capability:
            case "edit":
                return after_post(lambda p: chat.edit(thread, p.id, markdown=text))
            case "delete":
                return after_post(lambda p: chat.delete(thread, p.id))
            case "fetchMessage":
                return after_post(lambda p: chat.fetch_message(thread, p.id))
            case "history":
                return expect(chat.history(thread, direction="backward").take(1).run_drain())
            case "download":
                return expect(
                    chat.download(
                        thread, Attachment(id="conformance-missing"), max_bytes=1
                    ).run_drain()
                )
            case "files":
                return expect(
                    chat.post(thread, markdown=text, files=(conformance_file(self.rule),)),
                    self.track,
                )
            case "replyTo":
                return self.post().flat_map(
                    lambda target: expect(
                        chat.post(thread, markdown=text, reply_to=ReplyTo(message_id=target.id)),
                        self.track,
                    )
                )
            case "startThread":
                return after_post(lambda p: chat.start_thread(thread, p.id))
            case "getThread":
                return expect(chat.get_thread(thread))
            case "opener":
                return expect(chat.opener(thread))
            case "getUser":
                return self.user_posts().flat_map(
                    lambda event: expect(
                        chat.get_user(self.options.platform, event.message.author.id)
                    )
                )
            case "buttons":
                return expect(
                    chat.post(thread, markdown=text, actions=(conformance_button(self.rule),)),
                    self.track,
                )
            case "selects":
                return expect(
                    chat.post(thread, markdown=text, actions=(conformance_select(self.rule),)),
                    self.track,
                )
            case "modals":
                # Probing a modal requires the interaction hook and a clickable element.
                if self.options.interactions is None or not (
                    self.has("buttons") or self.has("selects")
                ):
                    return fx.void
                return self.open_modal(PROBE_MODAL.open()).and_then(self._check_refusal(capability))
            case "modalErrors":
                # Its absence means a degraded answer, not a refusal, so it has no inverse.
                return fx.void
            case "commands":
                # A deferral built by hand, which no adapter can follow up: it must fail, and
                # not with Unsupported when listed.
                command = ci.CommandInvoked(
                    id="conformance", text="", thread=thread, user_id="conformance", raw={}
                )
                return expect(chat.follow_up(ci.defer(command, visibility="public"), markdown=text))
            case "ephemeral":
                # Probing a private answer requires the command hook.
                if self.options.interactions is None or self.options.interactions.command is None:
                    return fx.void

                def private() -> Effect[None, ConformanceFailure]:
                    self.recording.on_command = lambda _: ci.respond(markdown=text)
                    return self.command("conformance").and_then(self._check_refusal(capability))

                return fx.suspend(private)
            case "nativeStream":
                listed = self.has(capability)

                def check_native(registry: Any) -> Effect[None, ConformanceFailure]:
                    return self.call(registry.get(self.options.platform)).flat_map(
                        lambda adapter: self.check(
                            (adapter.native_stream is not None) == listed,
                            "a native_stream, as the descriptor lists it"
                            if listed
                            else "no native_stream, as the descriptor lacks it",
                            lambda: (
                                "no native_stream"
                                if adapter.native_stream is None
                                else "a native_stream"
                            ),
                        )
                    )

                return Registry().flat_map(check_native)

    @property
    def cleanup(self) -> Effect[None]:
        def run() -> Effect[None]:
            if not self.has("delete"):
                return fx.void
            created = list(reversed(self.created))
            self.created.clear()
            return fx.for_each(
                created,
                lambda c: self.chat.delete(c.thread, c.id).ignore(),
                discard=True,
            )

        return fx.suspend(run)


__all__ = [
    "ConformanceFailure",
    "Interactions",
    "MentionToken",
    "NoSuchElement",
    "ParseMention",
    "check_event",
    "check_interaction",
    "check_message",
    "same_message",
]
