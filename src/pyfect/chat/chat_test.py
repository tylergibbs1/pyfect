"""A whole chat in memory, and the checks every adapter must pass (Effect's
``effect/chat/ChatTest``).

``chat_test.layer()`` gives ``Chat``, its ``Registry`` and one fake adapter,
with the ``ChatTest`` service to drive it: make threads, post as a user,
click, submit, fail the next call. ``conformance`` is the suite of rules a
real adapter must pass, as plain effects keyed by rule name, and
``check_message``, ``check_event`` and ``check_interaction`` check the
invariants of what an adapter reads::

    @fx.gen
    def program():
        test = yield from ChatTest()
        chat = yield from Chat()
        thread = yield from test.make_thread()
        yield from chat.post(thread, markdown="hello")
        return [m.text for m in (yield from test.messages(thread))]

    fx.run_blocking(program.pipe(fx.provide(chat_test.layer())))  # ['hello']
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Never, TypedDict, Unpack, overload

import pyfect as fx
from pyfect import clock as _clock
from pyfect import date_time as _date_time
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_value import JsonValue


# The two errors live here, before the imports of the conformance modules, which raise them.
class NoSuchElement(
    S.TaggedError, tag="NoSuchElement", identifier="effect/chat/ChatTest/NoSuchElement"
):
    """A click on an element the message does not carry."""

    message_id: str = S.field(S.String, key="messageId")
    id: str


class ConformanceFailure(
    S.TaggedError, tag="ConformanceFailure", identifier="effect/chat/ChatTest/ConformanceFailure"
):
    """A conformance rule or invariant that did not hold: ``rule`` names
    it, ``expected`` and ``actual`` say how; a platform error behind it is
    in ``cause``."""

    rule: str
    expected: str
    actual: str
    cause: object = S.field(S.Defect(), default=None)

    @property
    def message(self) -> str:
        return f"{self.rule}: expected {self.expected}, got {self.actual}"


from pyfect.chat import chat as _chat  # noqa: E402
from pyfect.chat import chat_interaction as ci  # noqa: E402
from pyfect.chat import chat_thread  # noqa: E402
from pyfect.chat import chat_ui as U  # noqa: E402
from pyfect.chat._chat_conformance import (  # noqa: E402
    Interactions,
    MentionToken,
    ParseMention,
    check_event,
    check_interaction,
    check_message,
    first_missing,
    same_message,
)
from pyfect.chat._chat_rules import Rule, conformance  # noqa: E402
from pyfect.chat._markdown_scan import well_formed  # noqa: E402
from pyfect.chat.chat_adapter import (  # noqa: E402
    AppendResult,
    Descriptor,
    Direction,
    File,
    Limits,
    Measure,
    NativeStream,
    Posted,
    Registry,
    ThreadInfo,
    User,
    check_message_length,
    retry_safe,
)
from pyfect.chat.chat_error import (  # noqa: E402
    CAPABILITIES,
    FILE_REFUSED,
    INTERACTION_EXPIRED,
    AnyReason,
    Capability,
    ChatError,
    Forbidden,
    InvalidRequest,
    NotFound,
    TooLarge,
    Unsupported,
)
from pyfect.chat.chat_event import ChatEvent, MessageCreated, ThreadKind  # noqa: E402
from pyfect.chat.chat_handler import ChatHandler, NotAccepted  # noqa: E402
from pyfect.chat.chat_message import (  # noqa: E402
    Attachment,
    Author,
    ChatMessage,
    Mention,
    MentionKind,
    ReplyTo,
    utf16_length,
)
from pyfect.chat.chat_thread import ChatThread  # noqa: E402
from pyfect.context import Tag  # noqa: E402
from pyfect.duration import Duration, minutes, zero  # noqa: E402
from pyfect.duration import Input as DurationInput  # noqa: E402
from pyfect.exit import Exit  # noqa: E402
from pyfect.layer import Layer  # noqa: E402
from pyfect.layer import effect as _layer_effect  # noqa: E402
from pyfect.layer import provide_merge as _provide_merge  # noqa: E402
from pyfect.result import Ok  # noqa: E402
from pyfect.stream import Stream  # noqa: E402
from pyfect.stream import _constructors as _stream  # noqa: E402
from pyfect.stream._concat import concat as _concat  # noqa: E402


@dataclass(frozen=True, kw_only=True)
class Call:
    """One call the fake adapter received, with what came of it: ``"ok"``
    or the failure reason's tag."""

    op: str
    thread: ChatThread
    message_id: str | None = None
    markdown: str | None = None
    files: tuple[File, ...] | None = None
    outcome: str


class LimitsOverrides(TypedDict, total=False):
    """The ``Limits`` fields to set on the fake's descriptor."""

    message_length: int
    files_per_message: int
    upload_bytes: int
    min_write_interval: Duration
    stream_length: int | None
    stream_age: Duration | None
    actions_per_message: int | None
    action_data_length: int | None
    modal_metadata_length: int | None
    modal_fields: int | None
    follow_up_age: Duration | None


type _From = ci.ButtonClicked | ci.SelectChanged | ci.CommandInvoked


def code_points(markdown: str, actions: Sequence[U.Action] = ()) -> int:
    """The fake's default ``measure``: the number of code points, actions
    free."""
    return len(markdown)


@dataclass
class _StoredStream:
    started_at: float
    open: bool = True
    clicked: bool = False


@dataclass(frozen=True, kw_only=True)
class _StoredThread:
    thread: ChatThread
    kind: ThreadKind
    created_at: datetime
    name: str | None = None
    parent: ChatThread | None = None
    opener_id: str | None = None


@dataclass(frozen=True)
class _StoredFile:
    attachment: Attachment
    content: bytes


@dataclass(kw_only=True)
class _StoredMessage:
    id: str
    thread: ChatThread
    author_id: str
    is_bot: bool
    is_self: bool
    text: str
    mentions: tuple[Mention, ...]
    reply_to: ReplyTo | None
    attachments: tuple[_StoredFile, ...]
    timestamp: datetime
    actions: tuple[U.Action, ...]


@dataclass
class _Fault:
    reason: AnyReason
    remaining: int
    landed: bool


@dataclass
class _Deferral:
    at: float
    used: bool = False


_HELD_BOUND = 100
_DOWNLOAD_CHUNK_SIZE = 1024
_MENTION = re.compile(r"<(@&|@|#|!)([^<>\s]+)>")
_MENTION_KINDS: dict[str, MentionKind] = {
    "@": "user",
    "@&": "role",
    "#": "channel",
    "!": "broadcast",
}


def _parse_mentions(text: str, self_id: str) -> tuple[Mention, ...]:
    mentions: list[Mention] = []
    for match in _MENTION.finditer(text):
        kind = _MENTION_KINDS[match.group(1)]
        start = utf16_length(text[: match.start()])
        mentions.append(
            Mention(
                kind=kind,
                id=match.group(2),
                start=start,
                end=start + utf16_length(match.group(0)),
                is_self=kind == "user" and match.group(2) == self_id,
            )
        )
    return tuple(mentions)


def _action_needs(actions: Sequence[U.Action]) -> list[Capability]:
    needs: list[Capability] = []
    if any(not isinstance(action, U.Select) for action in actions):
        needs.append("buttons")
    if any(isinstance(action, U.Select) for action in actions):
        needs.append("selects")
    return needs


def _answer_needs(visibility: ci.Visibility, actions: Sequence[U.Action] = ()) -> list[Capability]:
    first: list[Capability] = ["ephemeral"] if visibility == "ephemeral" else []
    return first + _action_needs(actions)


def _command_key(command: ci.CommandInvoked) -> str | None:
    raw = command.raw
    if isinstance(raw, dict):
        key = raw.get("id")
        if isinstance(key, str):
            return key
    return None


class _Fake:
    """The fake platform's state, and the ops over it."""

    def __init__(
        self,
        *,
        platform: str,
        self_id: str,
        capabilities: frozenset[Capability],
        limits: LimitsOverrides,
        measure: Measure,
        interaction_deadline: DurationInput,
    ) -> None:
        self.platform = platform
        self.self_id = self_id
        self.capabilities = capabilities
        self.interaction_deadline = interaction_deadline
        message_length = limits.get("message_length", 4000)
        has_actions = "buttons" in capabilities or "selects" in capabilities
        native = "nativeStream" in capabilities
        base = Limits(
            message_length=message_length,
            files_per_message=10,
            upload_bytes=10 * 1024 * 1024,
            min_write_interval=zero,
            stream_length=message_length if native else None,
            stream_age=minutes(10) if native else None,
            actions_per_message=25 if has_actions else None,
            action_data_length=100 if has_actions else None,
            modal_metadata_length=100 if "modals" in capabilities else None,
            modal_fields=5 if "modals" in capabilities else None,
            follow_up_age=minutes(15) if "commands" in capabilities else None,
        )
        self.descriptor = Descriptor(
            platform=platform,
            capabilities=capabilities,
            measure=measure,
            limits=dataclasses.replace(base, **limits),
        )
        self.streams: dict[str, _StoredStream] = {}
        self.threads: dict[str, _StoredThread] = {}
        self.messages: dict[str, _StoredMessage] = {}
        self.order: list[str] = []
        self.thread_under: dict[str, ChatThread] = {}
        self.users: dict[str, bool] = {self_id: True}
        self.calls: list[Call] = []
        self.deferrals: dict[str, _Deferral] = {}
        self.refused_files = 0
        self.faults: dict[str, list[_Fault]] = {}
        self.counter = 0

    # --- helpers ------------------------------------------------------------

    def next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}{self.counter}"

    def error(self, op: str, reason: AnyReason) -> ChatError:
        return ChatError(platform=self.platform, op=op, reason=reason)

    def fail(self, op: str, reason: AnyReason) -> Effect[Never, ChatError]:
        return fx.fail(self.error(op, reason))

    def to_message(self, message: _StoredMessage) -> ChatMessage:
        reply_to = message.reply_to
        if reply_to is not None and reply_to.author_id is not None:
            reply_to = ReplyTo(
                message_id=reply_to.message_id,
                author_id=reply_to.author_id,
                is_self=reply_to.author_id == self.self_id,
            )
        return ChatMessage(
            id=message.id,
            thread=message.thread,
            author=Author(
                id=message.author_id,
                name="test-bot" if message.is_self else message.author_id,
                is_bot=message.is_bot,
                is_self=message.is_self,
            ),
            text=message.text,
            mentions=message.mentions,
            reply_to=reply_to,
            attachments=tuple(stored.attachment for stored in message.attachments),
            timestamp=message.timestamp,
            raw={
                "type": "message",
                "id": message.id,
                "channel": message.thread.id,
                "user": message.author_id,
                "text": message.text,
            },
        )

    def find_thread(self, op: str, thread: ChatThread) -> Effect[_StoredThread, ChatError]:
        def find() -> Effect[_StoredThread, ChatError]:
            stored = self.threads.get(thread.id)
            if stored is None:
                return self.fail(op, NotFound(detail="thread_not_found"))
            return fx.succeed(stored)

        return fx.suspend(find)

    def list_messages(self, stored: _StoredThread) -> list[_StoredMessage]:
        found: list[_StoredMessage] = []
        if stored.opener_id is not None and stored.opener_id in self.messages:
            found.append(self.messages[stored.opener_id])
        for id in self.order:
            message = self.messages.get(id)
            if message is not None and chat_thread.equals(message.thread, stored.thread):
                found.append(message)
        return found

    def find_message(
        self, op: str, thread: ChatThread, message_id: str
    ) -> Effect[_StoredMessage, ChatError]:
        def find(stored: _StoredThread) -> Effect[_StoredMessage, ChatError]:
            for message in self.list_messages(stored):
                if message.id == message_id:
                    return fx.succeed(message)
            return self.fail(op, NotFound(detail="message_not_found"))

        return self.find_thread(op, thread).flat_map(find)

    def store(
        self,
        *,
        thread: ChatThread,
        author_id: str,
        is_bot: bool,
        is_self: bool,
        text: str,
        mentions: tuple[Mention, ...],
        reply_to: ReplyTo | None,
        attachments: tuple[_StoredFile, ...],
        actions: tuple[U.Action, ...],
    ) -> Effect[_StoredMessage]:
        def add(timestamp: datetime) -> _StoredMessage:
            stored = _StoredMessage(
                id=self.next_id("m"),
                thread=thread,
                author_id=author_id,
                is_bot=is_bot,
                is_self=is_self,
                text=text,
                mentions=mentions,
                reply_to=reply_to,
                attachments=attachments,
                timestamp=timestamp,
                actions=actions,
            )
            self.messages[stored.id] = stored
            self.order.append(stored.id)
            return stored

        return _date_time.now().map(add)

    def store_files(self, files: Sequence[File]) -> tuple[_StoredFile, ...]:
        return tuple(
            _StoredFile(
                Attachment(
                    id=self.next_id("f"),
                    name=file.name,
                    content_type=file.content_type,
                    size=len(file.content),
                ),
                file.content,
            )
            for file in files
        )

    def post_own(
        self,
        op: str,
        thread: ChatThread,
        *,
        text: str,
        reply_to: ReplyTo | None,
        attachments: tuple[_StoredFile, ...],
        actions: Sequence[U.Action],
    ) -> Effect[Posted, ChatError]:
        target: Effect[_StoredMessage | None, ChatError] = (
            fx.succeed(None)
            if reply_to is None
            else self.find_message(op, thread, reply_to.message_id)
        )

        def write(found: _StoredMessage | None) -> Effect[Posted]:
            return self.store(
                thread=thread,
                author_id=self.self_id,
                is_bot=True,
                is_self=True,
                text=text,
                mentions=(),
                reply_to=None
                if found is None
                else ReplyTo(message_id=found.id, author_id=found.author_id),
                attachments=attachments,
                actions=tuple(actions),
            ).map(lambda stored: Posted(stored.id, thread, stored.timestamp))

        return target.flat_map(write)

    def create_thread(
        self, op: str, thread: ChatThread, message_id: str, name: str | None
    ) -> Effect[ChatThread, ChatError]:
        def create(message: _StoredMessage) -> Effect[ChatThread, ChatError]:
            existing = self.thread_under.get(message.id)
            if existing is not None:
                return fx.succeed(existing)
            parent = self.threads[message.thread.id]
            if parent.kind == "thread" or not chat_thread.equals(message.thread, thread):
                return self.fail(op, InvalidRequest(detail="cannot_thread_reply"))

            def add(created_at: datetime) -> ChatThread:
                created = chat_thread.make(self.platform, f"{thread.id}/{message.id}")
                self.threads[created.id] = _StoredThread(
                    thread=created,
                    kind="thread",
                    name=name,
                    parent=thread,
                    opener_id=message.id,
                    created_at=created_at,
                )
                self.thread_under[message.id] = created
                return created

            return _date_time.now().map(add)

        return self.find_message(op, thread, message_id).flat_map(create)

    def check_actions(self, op: str, actions: Sequence[U.Action]) -> Effect[None, ChatError]:
        def check() -> Effect[None, ChatError]:
            limits = self.descriptor.limits
            if limits.actions_per_message is not None and len(actions) > limits.actions_per_message:
                return self.fail(op, TooLarge(detail="too_many_actions"))
            data: list[int] = []
            for action in actions:
                if isinstance(action, U.Button):
                    data.append(len(action.id) + len(action.value or ""))
                elif isinstance(action, U.Select):
                    data.extend(len(action.id) + len(option.value) for option in action.options)
            limit = limits.action_data_length
            if limit is not None and any(length > limit for length in data):
                return self.fail(op, TooLarge(detail="action_data_too_long"))
            return fx.void

        return fx.suspend(check)

    def modal_refusal(self, modal: U.Modal) -> ChatError | None:
        limits = self.descriptor.limits
        if "modals" not in self.capabilities:
            return self.error("openModal", Unsupported(capability="modals"))
        metadata = limits.modal_metadata_length
        if metadata is not None and len(modal.id) + len(modal.metadata or "") > metadata:
            return self.error("openModal", TooLarge(detail="modal_metadata_too_long"))
        if limits.modal_fields is not None and len(modal.elements) > limits.modal_fields:
            return self.error("openModal", TooLarge(detail="too_many_fields"))
        return None

    def take_fault(self, op: str) -> _Fault | None:
        queue = self.faults.get(op)
        if not queue:
            return None
        fault = queue[0]
        fault.remaining -= 1
        if fault.remaining <= 0:
            queue.pop(0)
        return fault

    def attempt[A](
        self,
        *,
        op: str,
        thread: ChatThread,
        needs: Sequence[Capability],
        body: Effect[A, ChatError],
        message_id: str | None = None,
        markdown: str | None = None,
        files: Sequence[File] | None = None,
        retries: bool = True,
    ) -> Effect[A, ChatError]:
        def record(outcome: str) -> None:
            self.calls.append(
                Call(
                    op=op,
                    thread=thread,
                    message_id=message_id,
                    markdown=markdown,
                    files=None if files is None else tuple(files),
                    outcome=outcome,
                )
            )

        def run() -> Effect[A, ChatError]:
            missing = first_missing(needs, self.descriptor.capabilities)
            if missing is not None:
                record("Unsupported")
                return self.fail(op, Unsupported(capability=missing))
            if op == "post" and files and self.refused_files > 0:
                self.refused_files -= 1
                record("Forbidden")
                return self.fail(op, Forbidden(detail=FILE_REFUSED))
            fault = self.take_fault(op)
            if fault is not None:
                record(fault.reason._tag)  # pyright: ignore[reportPrivateUsage]
                failure = self.fail(op, fault.reason)
                return body.exit().and_then(failure) if fault.landed else failure
            return body.tap(lambda _: fx.sync(lambda: record("ok"))).tap_error(
                lambda error: fx.sync(lambda: record(error.reason._tag))  # pyright: ignore[reportPrivateUsage]
            )

        attempted = fx.suspend(run)
        return retry_safe(attempted) if retries else attempted

    def is_open(self, message_id: str) -> Effect[bool]:
        def check(now: float) -> bool:
            stream = self.streams.get(message_id)
            if stream is None or not stream.open:
                return False
            age = self.descriptor.limits.stream_age
            if age is not None and now - stream.started_at >= age.to_millis():
                stream.open = False
            return stream.open

        return _clock.current_time_millis().map(check)

    def stream_length(self) -> int:
        limits = self.descriptor.limits
        return limits.stream_length if limits.stream_length is not None else limits.message_length


class _FakeNativeStream(NativeStream):
    def __init__(self, fake: _Fake) -> None:
        self._fake = fake

    def start(
        self,
        thread: ChatThread,
        *,
        markdown: str,
        reply_to: ReplyTo | None = None,
        recipient: str | None = None,
        continues: str | None = None,
    ) -> Effect[Posted, ChatError]:
        fake = self._fake
        op = "nativeStream.start"

        @fx.gen
        def body() -> Generator[Effect[Any, ChatError, Never], Any, Posted]:
            yield from fake.find_thread(op, thread)
            yield from check_message_length(fake.descriptor, op, markdown)
            if fake.descriptor.measure(markdown, ()) > fake.stream_length():
                yield from fake.fail(op, TooLarge(subject="text", detail="msg_too_long"))
            posted: Posted = yield from fake.post_own(
                op,
                thread,
                text=well_formed(markdown),
                reply_to=reply_to,
                attachments=(),
                actions=(),
            )
            now: float = yield from _clock.current_time_millis()
            fake.streams[posted.id] = _StoredStream(now)
            return posted

        needs: list[Capability] = (
            ["nativeStream"] if reply_to is None else ["nativeStream", "replyTo"]
        )
        return fake.attempt(op=op, thread=thread, markdown=markdown, needs=needs, body=body)

    def append(
        self, thread: ChatThread, message_id: str, markdown: str, *, flush: bool = False
    ) -> Effect[AppendResult, ChatError]:
        fake = self._fake
        op = "nativeStream.append"

        @fx.gen
        def body() -> Generator[Effect[Any, ChatError, Never], Any, AppendResult]:
            message: _StoredMessage = yield from fake.find_message(op, thread, message_id)
            stream = fake.streams.get(message.id)
            is_open: bool = yield from fake.is_open(message.id)
            if stream is None or not is_open:
                stopped = stream is not None and stream.clicked
                return AppendResult("stopped" if stopped else "closed", 0)
            held = 0
            open_at = markdown.rfind("<")
            if not flush and open_at != -1 and ">" not in markdown[open_at:]:
                held = len(markdown) - open_at
                if held > _HELD_BOUND:
                    held = 0
            # A trailing high surrogate waits for its other half.
            if not flush and held == 0 and markdown and 0xD800 <= ord(markdown[-1]) <= 0xDBFF:
                held = 1
            sent = well_formed(markdown[: len(markdown) - held])
            if fake.descriptor.measure(message.text + sent, ()) > fake.stream_length():
                yield from fake.fail(op, TooLarge(subject="text", detail="msg_too_long"))
            message.text += sent
            return AppendResult("open", held)

        return fake.attempt(
            op=op,
            thread=thread,
            message_id=message_id,
            markdown=markdown,
            needs=["nativeStream"],
            body=body,
            retries=False,
        )

    def stop(
        self, thread: ChatThread, message_id: str, *, end: Literal["done", "rotating"]
    ) -> Effect[bool, ChatError]:
        fake = self._fake
        op = "nativeStream.stop"

        @fx.gen
        def body() -> Generator[Effect[Any, ChatError, Never], Any, bool]:
            message: _StoredMessage = yield from fake.find_message(op, thread, message_id)
            stream = fake.streams.get(message.id)
            is_open: bool = yield from fake.is_open(message.id)
            if stream is None or not is_open:
                return False
            stream.open = False
            return stream.clicked

        return fake.attempt(
            op=op, thread=thread, message_id=message_id, needs=["nativeStream"], body=body
        )


class _FakeAdapter:
    """The fake platform's ``ChatAdapter``."""

    def __init__(self, fake: _Fake) -> None:
        self._fake = fake
        self._native = _FakeNativeStream(fake) if "nativeStream" in fake.capabilities else None

    @property
    def descriptor(self) -> Descriptor:
        return self._fake.descriptor

    @property
    def native_stream(self) -> NativeStream | None:
        return self._native

    def post(
        self,
        thread: ChatThread,
        *,
        markdown: str,
        reply_to: ReplyTo | None = None,
        files: Sequence[File] = (),
        actions: Sequence[U.Action] = (),
    ) -> Effect[Posted, ChatError]:
        fake = self._fake
        needs: list[Capability] = []
        if files:
            needs.append("files")
        if reply_to is not None:
            needs.append("replyTo")
        needs.extend(_action_needs(actions))
        limits = fake.descriptor.limits

        @fx.gen
        def body() -> Generator[Effect[Any, ChatError, Never], Any, Posted]:
            yield from fake.find_thread("post", thread)
            yield from check_message_length(fake.descriptor, "post", markdown, actions)
            yield from fake.check_actions("post", actions)
            if len(files) > limits.files_per_message or any(
                len(file.content) > limits.upload_bytes for file in files
            ):
                yield from fake.fail("post", TooLarge(subject="files", detail=FILE_REFUSED))
            posted: Posted = yield from fake.post_own(
                "post",
                thread,
                text=markdown,
                reply_to=reply_to,
                attachments=fake.store_files(files),
                actions=actions,
            )
            return posted

        return fake.attempt(
            op="post", thread=thread, markdown=markdown, files=files, needs=needs, body=body
        )

    def edit(
        self,
        thread: ChatThread,
        message_id: str,
        *,
        markdown: str,
        actions: Sequence[U.Action] = (),
    ) -> Effect[None, ChatError]:
        fake = self._fake

        @fx.gen
        def body() -> Generator[Effect[Any, ChatError, Never], Any]:
            message: _StoredMessage = yield from fake.find_message("edit", thread, message_id)
            if not message.is_self:
                yield from fake.fail("edit", Forbidden(detail="cant_update_message"))
            if (yield from fake.is_open(message.id)):
                yield from fake.fail("edit", InvalidRequest(detail="streaming_state_conflict"))
            yield from check_message_length(fake.descriptor, "edit", markdown, actions)
            yield from fake.check_actions("edit", actions)
            message.text = markdown
            message.mentions = ()
            message.actions = tuple(actions)

        return fake.attempt(
            op="edit",
            thread=thread,
            message_id=message_id,
            markdown=markdown,
            needs=["edit", *_action_needs(actions)],
            body=body,
        )

    def delete(self, thread: ChatThread, message_id: str) -> Effect[None, ChatError]:
        fake = self._fake

        @fx.gen
        def body() -> Generator[Effect[Any, ChatError, Never], Any]:
            message: _StoredMessage = yield from fake.find_message("delete", thread, message_id)
            if not message.is_self:
                yield from fake.fail("delete", Forbidden(detail="cant_delete_message"))
            if (yield from fake.is_open(message.id)):
                yield from fake.fail("delete", InvalidRequest(detail="cant_delete_message"))
            del fake.messages[message.id]

        return fake.attempt(
            op="delete", thread=thread, message_id=message_id, needs=["delete"], body=body
        )

    def fetch_message(self, thread: ChatThread, message_id: str) -> Effect[ChatMessage, ChatError]:
        fake = self._fake
        return fake.attempt(
            op="fetchMessage",
            thread=thread,
            message_id=message_id,
            needs=["fetchMessage"],
            body=fake.find_message("fetchMessage", thread, message_id).map(fake.to_message),
        )

    def history(
        self, thread: ChatThread, *, direction: Direction, from_: str | None = None
    ) -> Stream[ChatMessage, ChatError]:
        fake = self._fake

        def page(stored: _StoredThread) -> Effect[Stream[ChatMessage], ChatError]:
            found = [fake.to_message(message) for message in fake.list_messages(stored)]
            if direction == "backward":
                found.reverse()
            if from_ is None:
                return fx.succeed(_stream.from_iterable(found))
            index = next((i for i, m in enumerate(found) if m.id == from_), None)
            if index is None:
                return fake.fail("history", NotFound(detail="message_not_found"))
            return fx.succeed(_stream.from_iterable(found[index + 1 :]))

        return _stream.unwrap(
            fake.attempt(
                op="history",
                thread=thread,
                message_id=from_,
                needs=["history"],
                body=fake.find_thread("history", thread).flat_map(page),
            )
        )

    def download(
        self, thread: ChatThread, attachment: Attachment, *, max_bytes: int
    ) -> Stream[bytes, ChatError]:
        fake = self._fake

        def read() -> Effect[Stream[bytes, ChatError], ChatError]:
            content: bytes | None = None
            for message in fake.messages.values():
                for stored in message.attachments:
                    if stored.attachment.id == attachment.id:
                        content = stored.content
            if content is None:
                return fake.fail("download", NotFound(detail="file_not_found"))
            chunks: list[bytes] = []
            for offset in range(0, min(len(content), max_bytes), _DOWNLOAD_CHUNK_SIZE):
                end = min(offset + _DOWNLOAD_CHUNK_SIZE, len(content))
                if end > max_bytes:
                    break
                chunks.append(content[offset:end])
            too_large: Stream[bytes, ChatError] = (
                _stream.fail(fake.error("download", TooLarge(detail="max_bytes")))
                if len(content) > max_bytes
                else _stream.empty
            )
            return fx.succeed(_concat(_stream.from_iterable(chunks), too_large))

        return _stream.unwrap(
            fake.attempt(op="download", thread=thread, needs=["download"], body=fx.suspend(read))
        )

    def start_thread(
        self, thread: ChatThread, message_id: str, *, name: str | None = None
    ) -> Effect[ChatThread, ChatError]:
        fake = self._fake
        return fake.attempt(
            op="startThread",
            thread=thread,
            message_id=message_id,
            needs=["startThread"],
            body=fake.create_thread("startThread", thread, message_id, name),
        )

    def get_thread(self, thread: ChatThread) -> Effect[ThreadInfo, ChatError]:
        fake = self._fake

        def info(stored: _StoredThread) -> ThreadInfo:
            return ThreadInfo(
                thread=stored.thread,
                kind=stored.kind,
                name=stored.name,
                parent=stored.parent,
                created_at=stored.created_at,
                raw={"id": stored.thread.id, "kind": stored.kind},
            )

        return fake.attempt(
            op="getThread",
            thread=thread,
            needs=["getThread"],
            body=fake.find_thread("getThread", thread).map(info),
        )

    def opener(self, thread: ChatThread) -> Effect[ChatMessage | None, ChatError]:
        fake = self._fake

        def find(stored: _StoredThread) -> ChatMessage | None:
            opener = None if stored.opener_id is None else fake.messages.get(stored.opener_id)
            return None if opener is None else fake.to_message(opener)

        return fake.attempt(
            op="opener",
            thread=thread,
            needs=["opener"],
            body=fake.find_thread("opener", thread).map(find),
        )

    def get_user(self, id: str, *, in_: ChatThread | None = None) -> Effect[User, ChatError]:
        fake = self._fake

        def find() -> Effect[User, ChatError]:
            is_bot = fake.users.get(id)
            if is_bot is None:
                return fake.fail("getUser", NotFound(detail="user_not_found"))
            is_self = id == fake.self_id
            return fx.succeed(
                User(
                    id=id,
                    name="test-bot" if is_self else id,
                    is_bot=is_bot,
                    is_self=is_self,
                    raw={"id": id},
                )
            )

        return fake.attempt(
            op="getUser",
            thread=in_ if in_ is not None else chat_thread.make(fake.platform, ""),
            needs=["getUser"],
            body=fx.suspend(find),
        )

    def follow_up(
        self, deferred: ci.Defer, *, markdown: str, actions: Sequence[U.Action] = ()
    ) -> Effect[None, ChatError]:
        fake = self._fake

        @fx.gen
        def body() -> Generator[Effect[Any, ChatError, Never], Any]:
            key = _command_key(deferred.command)
            stored = None if key is None else fake.deferrals.get(key)
            age = fake.descriptor.limits.follow_up_age
            now: float = yield from _clock.current_time_millis()
            if (
                stored is None
                or stored.used
                or (age is not None and now - stored.at >= age.to_millis())
            ):
                yield from fake.fail("followUp", NotFound(detail=INTERACTION_EXPIRED))
                return
            yield from check_message_length(fake.descriptor, "followUp", markdown, actions)
            yield from fake.check_actions("followUp", actions)
            stored.used = True

        return fake.attempt(
            op="followUp",
            thread=deferred.command.thread,
            markdown=markdown,
            needs=["commands", *_answer_needs(deferred.visibility, actions)],
            body=body,
            retries=False,
        )


class Service:
    """Drives the fake platform: what a user does on it, and what it holds.

    - ``make_thread`` makes a channel, a direct address, or a thread under a
      user's opener.
    - ``user_posts`` stores a message from another identity and gives the
      ``MessageCreated`` the platform would deliver; ``deliver`` hands an
      event to ``ChatHandler``.
    - ``fail_next`` fails the next ``times`` calls of an op with ``reason``
      (``landed`` runs the call first, as a write that landed but answered
      with an error); ``refuse_files`` refuses the next posts with files.
    - ``click``, ``command`` and ``submit`` build the interaction the
      platform would send; ``interact`` runs it through
      ``chat_interaction.handle`` and carries out the reply as the platform
      would, calling ``Handler.refused`` when it cannot.
    """

    __slots__ = ("_fake",)

    def __init__(self, fake: _Fake) -> None:
        self._fake = fake

    @property
    def platform(self) -> str:
        """The fake platform's name."""
        return self._fake.platform

    @property
    def self_id(self) -> str:
        """The bot's own user id on the fake platform."""
        return self._fake.self_id

    def _add_thread(self, kind: Literal["channel", "direct"]) -> Effect[ChatThread]:
        fake = self._fake

        def add(created_at: datetime) -> ChatThread:
            thread = chat_thread.make(
                fake.platform, fake.next_id("c" if kind == "channel" else "d")
            )
            fake.threads[thread.id] = _StoredThread(thread=thread, kind=kind, created_at=created_at)
            return thread

        return _date_time.now().map(add)

    def make_thread(self, kind: ThreadKind = "channel") -> Effect[ChatThread]:
        """A new channel, direct address, or thread under a user's opener."""
        if kind != "thread":
            return self._add_thread(kind)

        @fx.gen
        def under_opener() -> Generator[Effect[Any, Never, Never], Any, ChatThread]:
            channel: ChatThread = yield from self._add_thread("channel")
            event: MessageCreated = yield from self.user_posts(channel, text="thread opener")
            created: ChatThread = yield from self._fake.create_thread(
                "makeThread", channel, event.message.id, None
            ).or_die()
            return created

        return under_opener

    def user_posts(
        self,
        thread: ChatThread,
        *,
        text: str,
        author_id: str = "user",
        is_bot: bool = False,
        mentions_self: bool = False,
        reply_to: ReplyTo | None = None,
        files: Sequence[File] = (),
    ) -> Effect[MessageCreated]:
        """Stores a message from another identity and gives the
        ``MessageCreated`` the platform would deliver."""
        fake = self._fake

        def post() -> Effect[MessageCreated]:
            stored = fake.threads.get(thread.id)
            if stored is None:
                return fx.die(RuntimeError("ChatTest.user_posts: unknown thread"))
            fake.users[author_id] = is_bot
            body = f"<@{fake.self_id}> {text}" if mentions_self else text
            target = None if reply_to is None else fake.messages.get(reply_to.message_id)
            # The author is read from the stored message, as a platform does, not from the caller.
            replied = (
                None
                if reply_to is None
                else ReplyTo(
                    message_id=reply_to.message_id,
                    author_id=None if target is None else target.author_id,
                )
            )
            return fake.store(
                thread=thread,
                author_id=author_id,
                is_bot=is_bot,
                is_self=False,
                text=body,
                mentions=_parse_mentions(body, fake.self_id),
                reply_to=replied,
                attachments=fake.store_files(files),
                actions=(),
            ).map(
                lambda created: MessageCreated(
                    thread=thread,
                    kind=stored.kind,
                    message=fake.to_message(created),
                    raw={"type": "event_callback", "event_id": fake.next_id("e")},
                )
            )

        return fx.suspend(post)

    def deliver(self, event: ChatEvent) -> Effect[None, NotAccepted, ChatHandler]:
        """Hands ``event`` to ``ChatHandler``."""
        return ChatHandler().flat_map(lambda handler: handler.handle(event))

    def messages(self, thread: ChatThread) -> Effect[tuple[ChatMessage, ...]]:
        """The messages stored in ``thread``, oldest first."""
        fake = self._fake

        def read() -> tuple[ChatMessage, ...]:
            stored = fake.threads.get(thread.id)
            if stored is None:
                return ()
            return tuple(fake.to_message(message) for message in fake.list_messages(stored))

        return fx.sync(read)

    @property
    def calls(self) -> Effect[tuple[Call, ...]]:
        """Every adapter call made so far, in order."""
        return fx.sync(lambda: tuple(self._fake.calls))

    def refuse_files(self, *, times: int = 1) -> Effect[None]:
        """Refuses the next ``times`` posts with files."""

        def refuse() -> None:
            self._fake.refused_files += times

        return fx.sync(refuse)

    def fail_next(
        self, op: str, reason: AnyReason, *, times: int = 1, landed: bool = False
    ) -> Effect[None]:
        """Fails the next ``times`` calls of ``op`` with ``reason``;
        ``landed`` runs the call first."""

        def add() -> None:
            if times == 0:
                return
            self._fake.faults.setdefault(op, []).append(_Fault(reason, times, landed))

        return fx.sync(add)

    def _stream_for(self, op: str, message_id: str) -> Effect[_StoredStream]:
        def find() -> Effect[_StoredStream]:
            stream = self._fake.streams.get(message_id)
            if stream is None:
                return fx.die(RuntimeError(f"ChatTest.{op}: no native stream {message_id}"))
            return fx.succeed(stream)

        return fx.suspend(find)

    def click_stop(self, message_id: str) -> Effect[None]:
        """Clicks stop on the native stream ``message_id``."""

        def click(stream: _StoredStream) -> None:
            stream.clicked = True

        return self._stream_for("click_stop", message_id).map(click)

    def close_stream(self, message_id: str) -> Effect[None]:
        """Closes the native stream ``message_id``, as its expiry would."""

        def close(stream: _StoredStream) -> None:
            stream.open = False

        return self._stream_for("close_stream", message_id).map(close)

    def click(
        self, message_id: str, id: str, *, user_id: str = "user", option: str | None = None
    ) -> Effect[ci.ButtonClicked | ci.SelectChanged, NoSuchElement]:
        """The click on element ``id`` of message ``message_id`` the platform
        would send (a select's ``option``)."""
        fake = self._fake

        def build() -> Effect[ci.ButtonClicked | ci.SelectChanged, NoSuchElement]:
            missing = fx.fail(NoSuchElement(message_id=message_id, id=id))
            message = fake.messages.get(message_id)
            element = (
                None
                if message is None
                else next(
                    (
                        action
                        for action in message.actions
                        if not isinstance(action, U.LinkButton) and action.id == id
                    ),
                    None,
                )
            )
            if message is None or element is None or isinstance(element, U.LinkButton):
                return missing
            raw: JsonValue = {
                "type": "interaction",
                "id": fake.next_id("i"),
                "message": message_id,
                "element": id,
            }
            if isinstance(element, U.Button):
                return fx.succeed(
                    ci.ButtonClicked(
                        id=id,
                        value=element.value,
                        thread=message.thread,
                        message_id=message_id,
                        user_id=user_id,
                        raw=raw,
                    )
                )
            chosen = (
                (element.options[0] if element.options else None)
                if option is None
                else next((o for o in element.options if o.value == option), None)
            )
            if chosen is None:
                return missing
            return fx.succeed(
                ci.SelectChanged(
                    id=id,
                    value=chosen.value,
                    thread=message.thread,
                    message_id=message_id,
                    user_id=user_id,
                    raw=raw,
                )
            )

        return fx.suspend(build)

    def command(
        self, thread: ChatThread, id: str, *, text: str = "", user_id: str = "user"
    ) -> Effect[ci.CommandInvoked]:
        """The slash command the platform would send."""
        fake = self._fake
        return fx.sync(
            lambda: ci.CommandInvoked(
                id=id,
                text=text,
                thread=thread,
                user_id=user_id,
                raw={"type": "command", "id": fake.next_id("i"), "command": id, "text": text},
            )
        )

    def submit(
        self,
        from_: _From,
        opened: ci.OpenModal,
        values: Mapping[str, str],
        *,
        user_id: str | None = None,
    ) -> Effect[ci.ModalSubmitted]:
        """The submit of an open modal the platform would send."""
        fake = self._fake
        return fx.sync(
            lambda: ci.ModalSubmitted(
                id=opened.modal.id,
                metadata=opened.modal.metadata,
                values={key: value for key, value in values.items() if value != ""},
                thread=from_.thread,
                message_id=None if isinstance(from_, ci.CommandInvoked) else from_.message_id,
                user_id=user_id if user_id is not None else from_.user_id,
                raw={"type": "submission", "id": fake.next_id("i"), "modal": opened.modal.id},
            )
        )

    @overload
    def interact(
        self, event: ci.ButtonClicked | ci.SelectChanged
    ) -> Effect[ci.ClickReply | ci.Late, Never, ci.Handler]: ...
    @overload
    def interact(
        self, event: ci.ModalSubmitted
    ) -> Effect[ci.SubmitReply | ci.Late, Never, ci.Handler]: ...
    @overload
    def interact(
        self, event: ci.CommandInvoked
    ) -> Effect[ci.CommandReply | ci.Late, Never, ci.Handler]: ...
    @overload
    def interact(self, event: ci.Interaction) -> Effect[Any, Never, ci.Handler]: ...
    def interact(self, event: ci.Interaction) -> Effect[Any, Never, ci.Handler]:
        """Runs ``event`` through ``chat_interaction.handle`` and carries out
        the reply as the platform would, calling ``Handler.refused`` when it
        cannot."""
        fake = self._fake

        @fx.gen
        def run() -> Generator[Effect[Any, Never, ci.Handler], Any, object]:
            reply: object = yield from ci.handle(event, fake.interaction_deadline)
            if isinstance(event, ci.ModalSubmitted):
                return reply
            refusal: ChatError | None = None
            match reply:
                case ci.OpenModal():
                    refusal = fake.modal_refusal(reply.modal)
                    fake.calls.append(
                        Call(
                            op="openModal",
                            thread=event.thread,
                            message_id=None
                            if isinstance(event, ci.CommandInvoked)
                            else event.message_id,
                            outcome="ok" if refusal is None else refusal.reason._tag,  # pyright: ignore[reportPrivateUsage]
                        )
                    )
                case ci.Respond():
                    actions = reply.actions or ()
                    exit = yield from fake.attempt(
                        op="respond",
                        thread=event.thread,
                        markdown=reply.markdown,
                        needs=_answer_needs(reply.visibility, actions),
                        body=check_message_length(
                            fake.descriptor, "respond", reply.markdown, actions
                        ).and_then(fake.check_actions("respond", actions)),
                        retries=False,
                    ).exit()
                    refusal = _error_of(exit)
                case ci.Defer():
                    missing = first_missing(_answer_needs(reply.visibility), fake.capabilities)
                    if missing is not None:
                        refusal = fake.error("defer", Unsupported(capability=missing))
                    else:
                        key = _command_key(event) if isinstance(event, ci.CommandInvoked) else None
                        if key is not None:
                            now: float = yield from _clock.current_time_millis()
                            fake.deferrals[key] = _Deferral(now)
                case _:
                    pass
            if refusal is not None:
                handler: ci.HandlerService = yield from ci.Handler()
                yield from handler.refused(event, refusal)
            return reply

        return run


def _error_of[E](exit: Exit[Any, E]) -> E | None:
    found = exit.find_error()
    return found.value if isinstance(found, Ok) else None


class ChatTest(Tag[Service], key="effect/chat/ChatTest"):
    """The fake platform's driver, from ``chat_test.layer``."""


def layer(
    *,
    platform: str = "test",
    self_id: str = "bot",
    capabilities: Sequence[Capability] = CAPABILITIES,
    measure: Measure = code_points,
    interaction_deadline: DurationInput = "3 seconds",
    **limits: Unpack[LimitsOverrides],
) -> Layer[_chat.Chat | Registry | ChatTest]:
    """A whole chat in memory: ``Chat``, its registry and one fake adapter.

    - Every capability is on by default; ``measure`` counts code points.
    - The default limits are 4000 per message and 10 files of up to 10 MiB.
      With ``nativeStream`` a stream takes up to ``message_length`` and
      lasts 10 minutes; with ``buttons`` or ``selects`` a message takes 25
      elements and an element's id plus encoded value 100 code points; with
      ``modals`` a modal's id plus metadata takes 100 and a modal 5 fields;
      with ``commands`` ``follow_up_age`` is 15 minutes. Keyword arguments
      named after ``Limits`` fields override them.
    - The native stream behaves the way Slack's was found to: an append
      past ``stream_length`` fails ``TooLarge`` and adds nothing, a stream
      past ``stream_age`` on ``Clock`` is closed, an append without
      ``flush`` holds back an unclosed ``<`` tail of up to 100 characters or
      a trailing high surrogate, and an open stream refuses ``edit`` and
      ``delete``.
    - ``interact`` gives a handler 3 seconds by default, on ``Clock``.
    - Two layers merged with different platforms share one ``Chat``, so
      routing can be tested; the ``ChatTest`` in context is the last one.
    """

    @fx.gen
    def make() -> Generator[Effect[Any, Never, Registry], Any, Service]:
        registry = yield from Registry()
        fake = _Fake(
            platform=platform,
            self_id=self_id,
            capabilities=frozenset(capabilities),
            limits=limits,
            measure=measure,
            interaction_deadline=interaction_deadline,
        )
        yield from registry.register(_FakeAdapter(fake))
        return Service(fake)

    return _layer_effect(ChatTest, make).pipe(_provide_merge(_chat.layer))


__all__ = [
    "Call",
    "ChatTest",
    "ConformanceFailure",
    "Interactions",
    "LimitsOverrides",
    "MentionToken",
    "NoSuchElement",
    "NotAccepted",
    "ParseMention",
    "Rule",
    "Service",
    "check_event",
    "check_interaction",
    "check_message",
    "code_points",
    "conformance",
    "layer",
    "same_message",
]
