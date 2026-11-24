"""Posting long and streamed Markdown through ``Chat`` (Effect's
``effect/chat/ChatMarkdown``).

``post`` splits Markdown that outgrows one message into parts at block
boundaries. ``stream`` writes a stream of Markdown deltas as it arrives:
by the adapter's native stream when it has one, otherwise by posting and
then editing, and on an adapter without ``edit`` by posting each part once.
Both use one splitter::

    @fx.gen
    def reply(deltas: Stream[str]):
        result = yield from chat_markdown.stream(chat_thread.make("slack", "T1/C1"), deltas)
        return [part.message_id for part in result.parts]
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, Literal, Never, TypeVar, cast

import pyfect as fx
from pyfect import clock as _clock
from pyfect import errors as _errors
from pyfect import exit as _exit
from pyfect._core import Effect, _call_user
from pyfect._fiber import Fiber
from pyfect._js import text_encode
from pyfect.cause import Cause as CauseOf
from pyfect.chat import chat as _chat
from pyfect.chat._markdown_scan import (
    Fence,
    closing,
    fence_at,
    fit_cut,
    is_blank,
    last_content_start,
    releasable,
    render,
    reopening,
    scan_lines,
    utf8_length,
)
from pyfect.chat.chat_adapter import Descriptor, File, NativeStream, Posted, Registry
from pyfect.chat.chat_error import FILE_REFUSED, ChatError, TooLarge, Unsupported
from pyfect.chat.chat_message import ReplyTo
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.chat_ui import Action
from pyfect.duration import Duration, millis, seconds
from pyfect.exit import Exit, Failure, Success
from pyfect.latch import Latch
from pyfect.result import Ok
from pyfect.scope import CloseableScope
from pyfect.stream import Stream
from pyfect.stream._base import require_stream
from pyfect.tracer._spans import annotate_current_span

# --- models --------------------------------------------------------------------------


@dataclass(frozen=True)
class Part:
    """One message a call created.

    - ``markdown`` is what went out, with a reopened or closed code fence
      and an unattached note included; empty for the overflow file.
    - ``text`` is the slice of the input the part carries: the ``text`` of
      every part, in order, is the input.
    - ``transport`` is ``"post"`` for a part from ``post`` and a streamed
      part posted once to an adapter without ``edit``, ``"edit"`` for one
      written by post-then-edit, ``"native"`` for one written by the
      adapter's native stream.
    """

    message_id: str
    timestamp: datetime
    markdown: str
    text: str
    kind: Literal["text", "overflowFile"]
    transport: Literal["post", "edit", "native"]


@dataclass(frozen=True)
class Result:
    """What a call posted: ``parts`` is empty when the input was empty;
    ``stopped`` means a user clicked stop on the reply (always ``False``
    from ``post``)."""

    parts: tuple[Part, ...]
    stopped: bool


@dataclass(frozen=True)
class ChatCause:
    """A write failed with ``error``."""

    error: ChatError
    _tag: Literal["Chat"] = field(default="Chat", init=False, repr=False)


E_co = TypeVar("E_co", covariant=True)


@dataclass(frozen=True)
class UpstreamCause(Generic[E_co]):
    """The deltas failed with ``error``."""

    error: E_co
    _tag: Literal["Upstream"] = field(default="Upstream", init=False, repr=False)


@dataclass(frozen=True)
class OverflowCause:
    """The input outgrew ``max_parts`` and the overflow file."""

    _tag: Literal["Overflow"] = field(default="Overflow", init=False, repr=False)


type Cause[E] = ChatCause | UpstreamCause[E] | OverflowCause


@dataclass(eq=False)
class ChatMarkdownError[E = Never](_errors.TaggedError):
    """A call that did not deliver its whole input.

    - ``posted`` is text the platform confirmed, ``uncertain`` text sent in a
      write that failed ``"uncertain"`` and was never confirmed since,
      ``remaining`` text never sent: ``posted``, then ``uncertain``, then
      ``remaining`` is the input.
    - ``remaining_fence`` is the line that opened the code fence
      ``remaining`` starts in, when it does: text sent later starts with it
      and a newline.
    - ``cause`` is a write's ``ChatError``, the deltas' error, or
      ``OverflowCause``.

    It carries message text, so ``message``, ``str()`` and ``to_json`` leave
    the text out.
    """

    posted: tuple[Part, ...]
    remaining: str
    cause: Cause[E]
    remaining_fence: str | None = None
    uncertain: str | None = None

    @property
    def message(self) -> str:
        cause = self.cause
        what = (
            f"Chat({cause.error.reason._tag})"  # pyright: ignore[reportPrivateUsage]
            if isinstance(cause, ChatCause)
            else cause._tag  # pyright: ignore[reportPrivateUsage]
        )
        return f"ChatMarkdown failed after {len(self.posted)} part(s): {what}"

    def __str__(self) -> str:
        return self.message

    def to_json(self) -> object:
        """The error without its message text."""
        cause = self.cause
        return {
            "_tag": "ChatMarkdownError",
            "posted": [
                {"messageId": p.message_id, "kind": p.kind, "transport": p.transport}
                for p in self.posted
            ],
            "cause": {"_tag": "Chat", "error": cause.error.to_json()}
            if isinstance(cause, ChatCause)
            else {"_tag": cause._tag},  # pyright: ignore[reportPrivateUsage]
        }


@dataclass(frozen=True)
class OverflowFile:
    """``overflow=OverflowFile(name)`` sends the text past ``max_parts`` as
    one trailing Markdown file named ``name``."""

    name: str


# --- the reply -----------------------------------------------------------------------

_DEFAULT_MAX_PARTS = 5
_APPEND_RETRY_LIMIT = 3  # Consecutive retry failures of appends on one stream before the repair.
_SOFT_SHARE = 0.85  # A native stream rolls over at the next boundary past this share of its length.
_AGE_SHARE = 0.8  # A native stream rotates once it is this share of its age old.
_FINISH_TIMEOUT = seconds(5)  # How long finishing a failed or interrupted reply may take.

type _Transport = Literal["post", "edit", "native"]


def _repaired(part: _Current, stopped: bool) -> None:
    part.attempted = -1
    if stopped:
        part.stopped_at = max(part.uncertain, part.sent)


@dataclass
class _Closing:
    end: Literal["done", "rotating"]
    on_stop: Callable[[_Current, bool], None]  # Given the part, so it holds no cell to it.


@dataclass
class _Current:
    start: int
    fence: Fence | None
    prefix: str
    transport: _Transport
    native: bool  # Appending to an open native stream.
    posted: Posted | None = None
    confirmed: int = 0  # The input index the platform confirmed up to.
    uncertain: int = 0  # The input index a write that failed uncertain reached.
    sent: int = 0  # Native: the input index appended up to.
    attempted: int = -1  # The input length when this part was last written.
    markdown: str = ""  # The Markdown the platform last confirmed.
    started_at: float = 0
    retries: int = 0
    closing: _Closing | None = None  # A stop to send, kept until the platform answers.
    stopped_at: int | None = None  # A user clicked stop during a repair: write up to here.


def _first_error[A](exit: Exit[A, ChatError]) -> ChatError | None:
    found = exit.find_error()
    return found.value if isinstance(found, Ok) else None


def _unanswered(exit: Exit[Any, ChatError]) -> bool:
    """Whether a write was cut off before the platform answered."""
    return isinstance(exit, Failure) and exit.cause.has_interrupts_only


def _is_file_refusal(exit: Exit[Any, ChatError]) -> bool:
    """Whether the adapter guarantees the files were refused and nothing
    remains posted."""
    error = _first_error(exit)
    return error is not None and error.retry == "denied" and error.reason.detail == FILE_REFUSED


@dataclass(frozen=True, kw_only=True)
class _Settings[E, R]:
    thread: ChatThread
    initial: str
    descriptor: Descriptor
    chat: _chat.Service
    deltas: Stream[str, E, Any] | None = None
    native: NativeStream | None = None
    recipient: str | None = None
    reply_to: ReplyTo | None = None
    max_parts: int | None = None
    overflow: OverflowFile | None = None
    min_write_interval: Duration | None = None
    on_part: Callable[[Part], Effect[None, Never, R]] | None = None
    files: Sequence[File] = ()
    actions: Sequence[Action] = ()
    unattached_note: Callable[[Sequence[File]], str] | None = None


class _Reply[E, R]:
    """One call's state: what arrived, what the platform confirmed, and the
    part being written. Every write commits its answer to this state before
    an interrupt can land."""

    def __init__(self, settings: _Settings[E, R]) -> None:
        self.s = settings
        descriptor = settings.descriptor
        limits = descriptor.limits
        self.limits = limits
        self.interval = (
            settings.min_write_interval
            if settings.min_write_interval is not None
            else limits.min_write_interval
        ).to_millis()
        self.max_parts: float = max(
            1, settings.max_parts if settings.max_parts is not None else _DEFAULT_MAX_PARTS
        )
        stream_length = (
            limits.stream_length if limits.stream_length is not None else limits.message_length
        )
        self.stream_length = min(stream_length, limits.message_length)
        self.stream_age = None if limits.stream_age is None else limits.stream_age.to_millis()
        self.latch = Latch()
        self.upstream_failed = Latch()  # Opens when the upstream fails, ending the loop at once.
        self.writes = CloseableScope()  # Holds the write fibers, so the finalizer can wait.
        self.input = settings.initial
        self.upstream: Exit[None, E] | None = _exit.void if settings.deltas is None else None
        self.state: Literal["Running", "Done", "Failed"] = "Running"
        self.stopped = False
        self.failure: Cause[E] | None = None
        self.finishing = False
        self.native_allowed = settings.native is not None and settings.recipient is not None
        # Without edit, a streamed part is posted once, when it is final.
        self.buffered = settings.deltas is not None and "edit" not in descriptor.capabilities
        self.rendered_natively = False
        self.last_write = float("-inf")
        self.retry_at: float | None = None
        self.overflow_start: int | None = None
        self.overflow_bytes = 0
        self.overflow_uncertain = False
        self.overflow_files_refused = False
        self.note: str | None = None
        self.parts: list[Part] = []
        self.inflight: Fiber[Any, Any] | None = None
        self.has_files = len(settings.files) > 0
        self.actions = tuple(settings.actions)
        self.has_actions = len(self.actions) > 0
        self.has_extras = self.has_files or self.has_actions
        # Set when not even the text's last cluster fits beside the actions: the files and the
        # actions follow the text in a message of their own.
        self.extras_alone = False
        self.note_actions = False  # Whether the note posted on its own takes the actions.
        self.actions_after = False  # The actions fit beside neither text nor note.
        self.current = self.new_part(0, None)

    # --- state ------------------------------------------------------------------------

    def measure(self, markdown: str) -> int:
        return self.s.descriptor.measure(markdown, ())

    def measure_last(self, markdown: str) -> int:
        """What the reply's last part costs, with the actions it carries."""
        return self.s.descriptor.measure(markdown, self.actions)

    def is_running(self) -> bool:
        return self.state == "Running"

    def fail(self, cause: Cause[E]) -> None:
        if self.is_running():
            self.state = "Failed"
            self.failure = cause

    def fail_chat(self, error: ChatError) -> None:
        self.fail(ChatCause(error))

    def done(self, stopped: bool) -> None:
        if self.is_running():
            self.state = "Done"
            self.stopped = stopped

    def new_part(self, start: int, fence: Fence | None) -> _Current:
        transport: _Transport = (
            "post"
            if self.s.deltas is None
            else "native"
            if self.native_allowed
            else "post"
            if self.buffered
            else "edit"
        )
        return _Current(
            start=start,
            fence=fence,
            prefix=reopening(fence),
            transport=transport,
            native=self.native_allowed,
            confirmed=start,
            uncertain=start,
            sent=start,
        )

    def part_of(
        self,
        posted: Posted,
        markdown: str,
        text: str,
        kind: Literal["text", "overflowFile"],
        transport: _Transport,
    ) -> Part:
        return Part(posted.id, posted.timestamp, markdown, text, kind, transport)

    def to_part(self, part: _Current, posted: Posted, markdown: str, end: int) -> Part:
        return self.part_of(posted, markdown, self.input[part.start : end], "text", part.transport)

    def first_reply_to(self) -> ReplyTo | None:
        """Only the reply's first message replies to ``reply_to``."""
        return self.s.reply_to if not self.parts else None

    def fence_at_input(self, part: _Current, index: int) -> Fence | None:
        """The open fence at ``index``, read from the part's complete lines."""
        text = self.input[part.start : index]
        return fence_at(scan_lines(text, part.fence, False), part.fence, len(text))

    def finish_part(self, end: int) -> None:
        part = self.current
        assert part.posted is not None
        self.parts.append(self.to_part(part, part.posted, part.markdown, end))
        self.current = self.new_part(end, self.fence_at_input(part, end))
        if len(self.parts) >= self.max_parts:
            self.overflow_start = end
            self.overflow_bytes = utf8_length(self.input[end:])

    def finish_reply(self, from_: int) -> None:
        """Ends the reply; blank text left over goes to the last part."""
        rest = self.input[from_:]
        if rest and self.parts:
            last = self.parts[-1]
            self.parts[-1] = Part(
                last.message_id,
                last.timestamp,
                last.markdown,
                last.text + rest,
                last.kind,
                last.transport,
            )
        self.done(False)

    # --- writing ----------------------------------------------------------------------

    def now(self) -> Effect[float]:
        return _clock.current_time_millis()

    def pace(self) -> Effect[None]:
        """Waits for the floor since the previous write returned."""

        def wait(time: float) -> Effect[None]:
            remaining = self.last_write + self.interval - time
            return fx.sleep(millis(remaining)) if remaining > 0 else fx.void

        return fx.suspend(lambda: self.now().flat_map(wait))

    def wrote(self) -> Effect[None]:
        def mark(time: float) -> None:
            self.last_write = time

        return self.now().map(mark)

    def write[A](
        self, effect: Effect[A, ChatError], commit: Callable[[Exit[A, ChatError]], None]
    ) -> Effect[None]:
        """Sends an edit or a stop after the floor. Both are safe to send
        again, so they stay interruptible; ``commit`` records the answer, or
        that there was none, before an interrupt can land."""
        return self.pace().and_then(
            fx.uninterruptible_mask(
                lambda restore: (
                    restore(effect)
                    .exit()
                    .ensuring(self.wrote())
                    .flat_map(lambda exit: fx.sync(lambda: commit(exit)))
                )
            )
        )

    def send[A](
        self,
        effect: Effect[A, ChatError],
        commit: Callable[[Exit[A, ChatError], float], Effect[None, Never, R]],
    ) -> Effect[Exit[A, ChatError], Never, R]:
        """Sends a post, a start or an append after the floor. Sending one
        again could repeat text, so neither an interrupt of the reply nor a
        failure of the upstream cuts it off: it runs in a fiber of its own,
        which commits the answer, and the finalizer waits for it. Only the
        finish timeout cuts it off."""

        def clear() -> None:
            self.inflight = None

        def request(restore_request: fx.Restore) -> Effect[Exit[A, ChatError], Never, R]:
            return (
                restore_request(effect)
                .exit()
                .ensuring(self.wrote())
                .tap(lambda exit: self.now().flat_map(lambda time: commit(exit, time)))
                .ensuring(fx.sync(clear))
            )

        def body(restore: fx.Restore) -> Effect[Exit[A, ChatError], Never, R]:
            def track(fiber: Fiber[Exit[A, ChatError], Never]) -> Effect[Exit[A, ChatError]]:
                self.inflight = fiber
                return restore(fiber.join())

            return fx.uninterruptible_mask(request).fork_in(self.writes).flat_map(track)

        return self.pace().and_then(fx.uninterruptible_mask(body))

    def create(
        self,
        effect: Effect[Posted, ChatError],
        part: Callable[[Posted], Part],
        commit: Callable[[Exit[Posted, ChatError], float], None],
    ) -> Effect[Exit[Posted, ChatError], Never, R]:
        """Creates a message, records it and runs ``on_part`` for it in one
        commit, so an interrupt neither loses an id nor posts it twice."""
        on_part = self.s.on_part

        def committed(exit: Exit[Posted, ChatError], time: float) -> Effect[None, Never, R]:
            commit(exit, time)
            if isinstance(exit, Success) and on_part is not None:
                return _call_user(on_part, part(exit.value))
            return fx.void

        return self.send(effect, committed)

    # --- post-then-edit ---------------------------------------------------------------

    def write_edit(self, end: int, last: bool, with_files: bool) -> Effect[None, Never, R]:
        """Writes the current part as ``input[start:end]``; ``last`` marks its
        final write, ``with_files`` the reply's last part."""

        def run() -> Effect[None, Never, R]:
            part = self.current
            markdown = render(part.prefix, self.input[part.start : end], part.fence)
            part.attempted = len(self.input)
            if part.posted is None:
                return self.post_part(part, end, markdown, with_files and self.has_extras)
            if part.confirmed == end and part.markdown == markdown:
                return fx.void
            edit = self.s.chat.edit(self.s.thread, part.posted.id, markdown=markdown)

            def commit(exit: Exit[None, ChatError]) -> None:
                if isinstance(exit, Success):
                    part.confirmed = part.uncertain = end
                    part.markdown = markdown
                    return
                # Cut off, so it may have landed. The finalizer edits again.
                if _unanswered(exit):
                    part.uncertain = max(part.uncertain, end)
                error = _first_error(exit)
                if error is None:
                    return
                if error.retry == "uncertain":
                    part.uncertain = max(part.uncertain, end)
                if last or error.retry == "denied":
                    self.fail_chat(error)

            return self.write(edit if last else _chat.without_retries(edit), commit)

        return fx.suspend(run)

    def post_part(
        self, part: _Current, end: int, markdown: str, with_files: bool
    ) -> Effect[None, Never, R]:
        s = self.s
        files = s.files if with_files and self.has_files else None
        unattached_note = None if files is None else s.unattached_note
        with_actions = with_files and self.has_actions

        def settle(exit: Exit[Posted, ChatError], markdown: str) -> None:
            if isinstance(exit, Success):
                part.posted = exit.value
                part.markdown = markdown
                part.confirmed = part.uncertain = end
                return
            if _unanswered(exit):
                part.uncertain = end
            error = _first_error(exit)
            if error is None:
                return
            if error.retry == "uncertain":
                part.uncertain = end
            self.fail_chat(error)

        def attempt(
            markdown: str, files: Sequence[File] | None, fallback: bool, with_actions: bool
        ) -> Effect[Exit[Posted, ChatError], Never, R]:
            def commit(exit: Exit[Posted, ChatError], _time: float) -> None:
                # Left unsettled: the post goes out again without the files.
                if fallback and _is_file_refusal(exit):
                    return
                settle(exit, markdown)

            return self.create(
                s.chat.post(
                    s.thread,
                    markdown=markdown,
                    reply_to=self.first_reply_to(),
                    files=files or (),
                    actions=self.actions if with_actions else (),
                ),
                lambda posted: self.to_part(part, posted, markdown, end),
                commit,
            )

        def without_files() -> Effect[None, Never, R]:
            # Replace refused files with the unattached note.
            assert unattached_note is not None and files is not None
            text = unattached_note(files)
            if self.measure_last(markdown + text) <= self.limits.message_length:
                return attempt(markdown + text, None, False, with_actions).as_void()
            # The note is the last message now, so it takes the actions, or they follow it.
            self.note_actions = (
                with_actions
                and s.descriptor.measure(text, self.actions) <= self.limits.message_length
            )
            self.actions_after = with_actions and not self.note_actions
            # With no text to post, this part is the note.
            if is_blank(markdown):
                return attempt(text, None, False, self.note_actions).as_void()
            self.note = text
            return attempt(markdown, None, False, False).as_void()

        if self.overflow_files_refused and files is not None:
            return without_files()
        return attempt(markdown, files, unattached_note is not None, with_actions).flat_map(
            lambda exit: (
                without_files()
                if unattached_note is not None and _is_file_refusal(exit)
                else fx.void
            )
        )

    def post_after(self, text: str, with_actions: bool) -> Effect[None, Never, R]:
        """Posts a message after the text: the unattached note, or the
        actions alone."""

        def part(posted: Posted) -> Part:
            return self.part_of(posted, text, "", "text", "post")

        def commit(exit: Exit[Posted, ChatError], _time: float) -> None:
            if isinstance(exit, Success):
                self.parts.append(part(exit.value))
                return
            error = _first_error(exit)
            if error is not None:
                self.fail_chat(error)

        post = self.s.chat.post(
            self.s.thread, markdown=text, actions=self.actions if with_actions else ()
        )
        return self.create(post, part, commit).flat_map(
            lambda _: self.finish_after() if self.is_running() else fx.void
        )

    def finish_after(self) -> Effect[None, Never, R]:
        """Ends the reply once the text is posted: the unattached note that
        did not fit follows, then the actions when they fit beside neither.
        The actions' message counts against ``max_parts``."""

        def run() -> Effect[None, Never, R]:
            if self.note is not None:
                text = self.note
                self.note = None
                return self.post_after(text, self.note_actions)
            if self.actions_after:
                self.actions_after = False
                if len(self.parts) >= self.max_parts:
                    self.fail(OverflowCause())
                    return fx.void
                return self.post_after("", True)
            self.done(False)
            return fx.void

        return fx.suspend(run)

    def post_extras(self) -> Effect[None, Never, R]:
        """Posts the files and the actions in a message of their own after
        the text; with no part left the reply fails ``Overflow``."""

        def run() -> Effect[None, Never, R]:
            self.extras_alone = False
            if len(self.parts) >= self.max_parts:
                self.fail(OverflowCause())
                return fx.void
            part = self.new_part(len(self.input), None)
            self.current = part

            def after(_: None) -> Effect[None, Never, R]:
                if not self.is_running():
                    return fx.void
                self.finish_part(len(self.input))
                return self.finish_after()

            return self.post_part(part, len(self.input), "", True).flat_map(after)

        return fx.suspend(run)

    def step_edit(self, final: bool) -> Effect[None, Never, R]:
        def run() -> Effect[None, Never, R]:
            part = self.current
            limit = self.limits.message_length
            if part.stopped_at is not None:
                stopped_at = part.stopped_at

                # A user clicked stop during a repair: settle what was sent, then end.
                def stop(_: None) -> None:
                    if not self.is_running():
                        return
                    self.finish_part(part.confirmed)
                    self.done(True)

                return self.write_edit(stopped_at, False, False).map(stop)
            body = self.input[part.start :]
            if (
                part.posted is None
                and is_blank(body)
                and not (final and self.has_extras and not self.parts)
            ):
                if final:
                    self.finish_reply(part.start)
                return fx.void

            def end(last: bool) -> Effect[None, Never, R]:
                if not last or not self.is_running():
                    return fx.void
                return self.post_extras() if self.extras_alone else self.finish_after()

            def cut_at(cut: int) -> Effect[None, Never, R]:
                # Only blank text follows: this is the last part, with the files and actions.
                last = final and is_blank(self.input[cut:])

                def after(_: None) -> Effect[None, Never, R]:
                    if not self.is_running():
                        return fx.void
                    self.finish_part(len(self.input) if last else cut)
                    return end(last)

                return self.write_edit(cut, True, last and not self.extras_alone).flat_map(after)

            def last_fits(cut: int) -> bool:
                """A cut that would end the reply has to leave room for the actions."""
                return (
                    not final
                    or not self.has_actions
                    or self.extras_alone
                    or not is_blank(self.input[cut:])
                    or self.measure_last(
                        render(part.prefix, self.input[part.start : cut], part.fence)
                    )
                    <= limit
                )

            cut = (
                part.start + fit_cut(self.measure, body, part.fence, part.prefix, limit)
                if self.measure(render(part.prefix, body, part.fence)) > limit
                else len(self.input)
            )
            if not last_fits(cut):
                # Reserve the last cluster for a part with actions; if they can't fit
                # together, the actions go in their own message.
                keep = last_content_start(body)
                tail_start = part.start + keep
                tail_fence = self.fence_at_input(part, tail_start)
                tail = render(reopening(tail_fence), self.input[tail_start:], tail_fence)
                if keep > 0 and self.measure_last(tail) <= limit:
                    return cut_at(
                        part.start
                        + fit_cut(self.measure, body[:keep], part.fence, part.prefix, limit)
                    )
                self.extras_alone = True
            if cut < len(self.input):
                return cut_at(cut)
            if self.buffered and not final:
                # Nothing to post until the part is final: it rolls over or the reply ends.
                part.attempted = len(self.input)
                return fx.void

            def finished(_: None) -> Effect[None, Never, R]:
                if final and self.is_running():
                    self.finish_part(len(self.input))
                return end(final)

            return self.write_edit(
                len(self.input), final, final and not self.extras_alone
            ).flat_map(finished)

        return fx.suspend(run)

    # --- native -----------------------------------------------------------------------

    @property
    def native(self) -> NativeStream:
        assert self.s.native is not None
        return self.s.native

    def send_stop(self, part: _Current, closing_: _Closing) -> Effect[None]:
        """Sends the stop the part is closing with; its failures are
        ignored, since a stop carries no text."""
        assert part.posted is not None

        def commit(exit: Exit[bool, ChatError]) -> None:
            # Cut off, so the stream may still be open. The finalizer sends the stop again.
            if _unanswered(exit):
                return
            part.closing = None
            part.native = False
            closing_.on_stop(part, isinstance(exit, Success) and exit.value)

        return self.write(self.native.stop(self.s.thread, part.posted.id, end=closing_.end), commit)

    def roll_native(self, part: _Current, end: int, last: bool) -> None:
        """Ends a native part at ``end`` once its stop is answered."""

        def on_stop(_part: _Current, stopped: bool) -> None:
            self.finish_part(end)
            if stopped:
                self.done(True)
            elif last:
                self.finish_reply(end)

        part.closing = _Closing("done" if last else "rotating", on_stop)

    def repair(self, part: _Current) -> None:
        """Stops the stream and carries on by post-then-edit: the next edit
        writes the part's whole known text."""

        part.closing = _Closing("rotating", _repaired)

    def start_native(self, final: bool) -> Effect[None, Never, R]:
        def run() -> Effect[None, Never, R]:
            part = self.current
            pending = self.input[part.start :]
            text = pending if final else releasable(pending, part.fence)
            if is_blank(text):
                if final:
                    self.finish_reply(part.start)
                return fx.void
            part.attempted = len(self.input)
            # Measured with the closing fence, so a start leaves room to close it.
            whole = render(part.prefix, text, part.fence)
            cut = (
                fit_cut(self.measure, text, part.fence, part.prefix, self.stream_length)
                if self.measure(whole) > self.stream_length
                else len(text)
            )
            end = part.start + cut
            roll = cut < len(text)
            markdown = (
                render(part.prefix, text[:cut], part.fence) if roll or final else part.prefix + text
            )

            def commit(exit: Exit[Posted, ChatError], time: float) -> None:
                if isinstance(exit, Success):
                    self.rendered_natively = True
                    part.posted = exit.value
                    part.markdown = markdown
                    part.confirmed = part.uncertain = part.sent = end
                    part.started_at = time
                    if roll or final:
                        self.roll_native(part, end, not roll)
                    return
                if _unanswered(exit):
                    part.uncertain = end
                error = _first_error(exit)
                if error is None:
                    return
                if isinstance(error.reason, Unsupported) and not self.rendered_natively:
                    self.native_allowed = False
                    self.current = self.new_part(part.start, part.fence)
                    return
                if error.retry == "uncertain":
                    part.uncertain = end
                self.fail_chat(error)

            return self.create(
                self.native.start(
                    self.s.thread,
                    markdown=markdown,
                    reply_to=self.first_reply_to(),
                    continues=self.parts[-1].message_id if self.parts else None,
                    recipient=self.s.recipient,
                ),
                lambda posted: self.to_part(part, posted, markdown, end),
                commit,
            ).as_void()

        return fx.suspend(run)

    def next_append(self, part: _Current, final: bool, rotate: bool) -> tuple[str, str, bool]:
        """What the next append sends (``piece`` and a closing ``extra``),
        and whether the part ends after it. Every append leaves room to close
        the code fence it ends in; ``rotate`` sends just that closing fence."""
        pending = self.input[part.sent :]
        fence = self.fence_at_input(part, part.sent)
        lines = scan_lines(pending, fence, False)

        def size(text: str) -> int:
            return self.measure(part.markdown + text)

        def close_at(piece: str) -> str:
            return closing(fence_at(lines, fence, len(piece)), part.markdown + piece)

        close_only = ("", close_at(""), True)
        if rotate:
            return close_only
        soft = _SOFT_SHARE * self.stream_length
        piece = pending if final else releasable(pending, fence)
        reserve = (
            closing(
                fence_at(scan_lines(pending, fence, True), fence, len(pending)),
                part.markdown + pending,
            )
            if final
            else close_at(piece)
        )
        extra = reserve if final else ""
        if size(piece + reserve) <= soft:
            return (piece, extra, False)
        for line in lines:
            if not line.boundary or line.end > len(piece):
                continue
            measured = size(pending[: line.end])
            if measured > self.stream_length:
                break
            if measured >= soft:
                return (pending[: line.end], "", True)
        if size(piece + reserve) <= self.stream_length:
            return (piece, extra, False)
        cut = pending[: fit_cut(self.measure, pending, fence, part.markdown, self.stream_length)]
        # Not even the smallest cut fits with its closing fence: send just the closing fence.
        if size(cut + close_at(cut)) <= self.stream_length:
            return (cut, close_at(cut), True)
        return close_only

    def append_native(self, final: bool, rotate: bool) -> Effect[None, Never, R]:
        """Appends the next piece; what follows (a rollover, a repair or a
        retry) is recorded in the commit, so an interrupt can't lose it."""

        def run() -> Effect[None, Never, R]:
            part = self.current
            piece, extra, roll = self.next_append(part, final, rotate)
            if piece == "" and extra == "":
                if roll or final:
                    self.roll_native(part, part.sent, not roll)
                return fx.void
            part.attempted = len(self.input)
            markdown = piece + extra
            assert part.posted is not None

            def commit(exit: Exit[Any, ChatError], time: float) -> None:  # noqa: PLR0912
                if isinstance(exit, Success):
                    result = exit.value
                    if result.state == "stopped":
                        part.native = False
                        self.finish_part(part.sent)
                        self.done(True)
                    elif result.state == "closed":
                        part.native = False
                        part.attempted = -1
                    else:
                        added = max(0, len(markdown) - result.held)
                        part.retries = 0
                        part.sent += min(len(piece), added)
                        part.confirmed = part.uncertain = part.sent
                        part.markdown += markdown[:added]
                        if roll or (final and part.sent == len(self.input)):
                            self.roll_native(part, part.sent, not roll)
                    return
                # Cut off by the finish timeout, so it may have landed.
                if _unanswered(exit):
                    part.uncertain = part.sent + len(piece)
                    return
                error = _first_error(exit)
                if error is None:
                    return
                if isinstance(error.reason, TooLarge):
                    # Retry the chunk in the next part.
                    self.roll_native(part, part.sent, False)
                elif error.retry == "retry":
                    part.retries += 1
                    if part.retries >= _APPEND_RETRY_LIMIT:
                        self.repair(part)
                    else:
                        after = error.retry_after
                        self.retry_at = time + (
                            self.interval if after is None else after.to_millis()
                        )
                elif error.retry == "uncertain":
                    part.uncertain = part.sent + len(piece)
                    self.repair(part)
                else:
                    self.fail_chat(error)
                    part.closing = _Closing("done", lambda _part, _stopped: None)

            return self.send(
                self.native.append(self.s.thread, part.posted.id, markdown, flush=final or roll),
                lambda exit, time: fx.sync(lambda: commit(exit, time)),
            ).as_void()

        return fx.suspend(run)

    def step_native(self, final: bool) -> Effect[None, Never, R]:
        def run() -> Effect[None, Never, R]:
            part = self.current
            if part.posted is None:
                return self.start_native(final)
            age = self.stream_age
            if final or age is None:
                return self.append_native(final, False)
            return self.now().flat_map(
                lambda time: self.append_native(final, time - part.started_at >= _AGE_SHARE * age)
            )

        return fx.suspend(run)

    # --- overflow ---------------------------------------------------------------------

    def step_overflow(self, final: bool) -> Effect[None, Never, R]:
        def run() -> Effect[None, Never, R]:
            start = self.overflow_start
            assert start is not None
            rest = self.input[start:]
            overflow = self.s.overflow
            if is_blank(rest):
                if final:
                    self.finish_reply(start)
                return fx.void
            if overflow is None or self.overflow_bytes > self.limits.upload_bytes:
                self.fail(OverflowCause())
                return fx.void
            # The upload is skipped when the reply failed or was interrupted.
            if not final or self.finishing:
                if self.finishing:
                    self.done(False)
                return fx.void
            file = File(overflow.name, "text/markdown", text_encode(rest))

            def part(markdown: str) -> Callable[[Posted], Part]:
                return lambda posted: self.part_of(posted, markdown, rest, "overflowFile", "post")

            # Attach consumer files to the final message.
            def attempt(
                markdown: str, files: Sequence[File], fallback: bool
            ) -> Effect[Exit[Posted, ChatError], Never, R]:
                def commit(exit: Exit[Posted, ChatError], _time: float) -> None:
                    if isinstance(exit, Success):
                        self.parts.append(part(markdown)(exit.value))
                        self.overflow_start = len(self.input)
                        self.done(False)
                        return
                    if fallback and _is_file_refusal(exit):
                        return
                    if _unanswered(exit):
                        self.overflow_uncertain = True
                    error = _first_error(exit)
                    if error is None:
                        return
                    self.overflow_uncertain = error.retry == "uncertain"
                    self.fail_chat(error)

                return self.create(
                    self.s.chat.post(
                        self.s.thread,
                        markdown=markdown,
                        files=(file, *files),
                        actions=self.actions if self.has_actions else (),
                    ),
                    part(markdown),
                    commit,
                )

            files = self.s.files
            unattached_note = None if not files else self.s.unattached_note

            def after(exit: Exit[Posted, ChatError]) -> None:
                if unattached_note is None or not _is_file_refusal(exit):
                    return
                # The overflow file was refused too. Drain the rest through the normal
                # splitter, without files or another max_parts overflow.
                self.overflow_files_refused = True
                self.overflow_start = None
                self.max_parts = float("inf")
                self.native_allowed = False
                self.current.native = False

            return attempt("", files, unattached_note is not None).map(after)

        return fx.suspend(run)

    # --- the loop ---------------------------------------------------------------------

    def active(self) -> bool:
        """Whether there is a write to make; a stop is sent even after the
        reply failed."""
        return self.is_running() or self.current.closing is not None

    def has_work(self) -> bool:
        if not self.is_running() or self.upstream is not None or self.current.closing is not None:
            return True
        if self.overflow_start is not None:
            return not is_blank(self.input[self.overflow_start :]) and (
                self.s.overflow is None or self.overflow_bytes > self.limits.upload_bytes
            )
        part = self.current
        if len(self.input) <= part.attempted:
            return False
        if not part.native:
            return not is_blank(self.input[part.start :])
        if part.posted is None:
            return not is_blank(releasable(self.input[part.start :], part.fence))
        return releasable(self.input[part.sent :], self.fence_at_input(part, part.sent)) != ""

    def await_work(self) -> Effect[None]:
        """Waits until there is something to write, or a retry is due."""

        def run() -> Effect[None]:
            if self.retry_at is not None:
                at = self.retry_at
                self.retry_at = None
                return self.now().flat_map(
                    lambda time: fx.sleep(millis(at - time)) if time < at else fx.void
                )
            if self.has_work():
                return fx.void
            self.latch.close_unsafe()
            return self.latch.wait().and_then(self.await_work())

        return fx.suspend(run)

    def step(self, final: bool) -> Effect[None, Never, R]:
        closing_ = self.current.closing
        if closing_ is not None:
            return self.send_stop(self.current, closing_)
        if self.overflow_start is not None:
            return self.step_overflow(final)
        return self.step_native(final) if self.current.native else self.step_edit(final)

    def loop(self) -> Effect[None, Never, R]:
        def run() -> Effect[None, Never, R]:
            if not self.active():
                return fx.void

            def next_(_: None) -> Effect[None, Never, R]:
                if not self.active():
                    return fx.void
                if (
                    self.current.closing is None
                    and self.upstream is not None
                    and isinstance(self.upstream, Failure)
                ):
                    return fx.void
                # The write takes whatever arrived while it waited for the floor.
                return (
                    self.pace()
                    .and_then(fx.suspend(lambda: self.step(self.upstream is not None)))
                    .and_then(self.loop())
                )

            return self.await_work().flat_map(next_)

        return fx.suspend(run)

    def drain(self) -> Effect[None, Never, R]:
        return self.step(True).and_then(fx.suspend(self.drain)) if self.active() else fx.void

    def finish(self) -> Effect[None, Never, R]:
        """Writes what was received as the end of the reply, closing an open
        fence, within a short timeout."""

        def run() -> Effect[None, Never, R]:
            self.finishing = True

            # A write in flight commits first. Interruptible, so the timeout can cut it short.
            def await_inflight() -> Effect[None]:
                inflight = self.inflight
                return fx.void if inflight is None else inflight.await_exit().as_void()

            def interrupt_inflight() -> Effect[None]:
                inflight = self.inflight
                return fx.void if inflight is None else inflight.interrupt()

            return (
                fx.suspend(await_inflight)
                .and_then(fx.suspend(self.drain))
                .interruptible()
                .timeout_option(_FINISH_TIMEOUT)
                .and_then(fx.suspend(interrupt_inflight))
                .as_void()
            )

        return fx.suspend(run)

    def to_error(self, cause: Cause[E]) -> ChatMarkdownError[E]:
        posted = list(self.parts)
        uncertain = ""
        if self.overflow_start is not None:
            from_ = self.overflow_start
            if self.overflow_uncertain:
                uncertain = self.input[from_:]
                from_ = len(self.input)
        else:
            part = self.current
            if part.posted is not None:
                posted.append(self.to_part(part, part.posted, part.markdown, part.confirmed))
            from_ = max(part.confirmed, part.uncertain)
            uncertain = self.input[part.confirmed : from_]
        # Read from the start of the input, so it holds whichever part the cut fell in.
        fence = (
            None
            if from_ == len(self.input)
            else fence_at(scan_lines(self.input[:from_], None, False), None, from_)
        )
        return ChatMarkdownError(
            posted=tuple(posted),
            remaining=self.input[from_:],
            remaining_fence=None if fence is None else fence.line,
            uncertain=uncertain or None,
            cause=cause,
        )

    def consume(self) -> Effect[None, Never, Any]:
        deltas = self.s.deltas
        if deltas is None:
            return fx.void

        def take(chunk: str) -> Effect[None]:
            def add() -> None:
                self.input += chunk
                if self.overflow_start is not None:
                    self.overflow_bytes += utf8_length(chunk)
                self.latch.open_unsafe()

            return fx.sync(add)

        def ended(exit: Exit[None, E]) -> Effect[None]:
            def mark() -> None:
                self.upstream = exit
                self.latch.open_unsafe()
                if isinstance(exit, Failure):
                    self.upstream_failed.open_unsafe()

            return fx.sync(mark)

        return deltas.run_for_each(take).exit().flat_map(ended)

    def run(self) -> Effect[Result, ChatMarkdownError[E], Any]:
        @fx.gen
        def body():
            fiber = yield from self.consume().fork()
            # A failed upstream ends the loop at once, so the finish timeout starts even while
            # a write is in flight.
            yield from (
                self.loop()
                .race_first(self.upstream_failed.wait())
                .on_interrupt(fiber.interrupt().and_then(self.finish()))
            )
            yield from fiber.interrupt()
            upstream = self.upstream
            if isinstance(upstream, Failure) and self.state in ("Running", "Done"):
                cause = upstream.cause
                self.state = "Running"
                yield from self.finish()
                found = cause.find_error()
                if not isinstance(found, Ok):
                    # No typed error: a defect or an interruption, passed on as it is.
                    return (yield from fx.fail_cause(cast("CauseOf[Never]", cause)))
                self.state = "Failed"
                self.failure = UpstreamCause(found.value)
            elif self.current.closing is not None or self.inflight is not None:
                # The reply failed already, and the race cut off its stop or write. The
                # finish sends only that stop, within the timeout, and keeps the error.
                yield from self.finish()
            yield from annotate_current_span(
                "chat.markdown.transport",
                "native" if self.rendered_natively else self.current.transport,
            )
            if self.state == "Failed":
                assert self.failure is not None
                return (yield from fx.fail(self.to_error(self.failure)))
            return Result(tuple(self.parts), self.state == "Done" and self.stopped)

        return body.ensuring(self.writes.close(_exit.void))


# --- the calls -----------------------------------------------------------------------


def post[R = Never](
    thread: ChatThread,
    markdown: str,
    *,
    reply_to: ReplyTo | None = None,
    max_parts: int | None = None,
    overflow: OverflowFile | None = None,
    min_write_interval: Duration | None = None,
    on_part: Callable[[Part], Effect[None, Never, R]] | None = None,
    files: Sequence[File] = (),
    actions: Sequence[Action] = (),
    unattached_note: Callable[[Sequence[File]], str] | None = None,
) -> Effect[Result, ChatMarkdownError, _chat.Chat | R]:
    """Posts Markdown of any length, split into as many messages as it needs.

    - A part ends at a block boundary: after a blank line or a closed code
      fence. A block too long for one message is cut at a line, closing the
      fence it is in and reopening it in the next part, measured with the
      adapter's ``measure``. Each part is posted once, paced by
      ``min_write_interval`` (default: the adapter's).
    - ``reply_to`` applies to the first part. ``max_parts`` defaults to 5;
      past it the call fails ``Overflow``, or with
      ``overflow=OverflowFile(name)`` sends the rest as one trailing file.
    - ``files`` go with the last part, or with the overflow file. With
      ``unattached_note``, a post whose files are refused (``"denied"`` with
      detail ``file_refused``) is tried once more without them, ending in
      the note, or followed by it when it does not fit.
    - ``actions`` go with the last part, cut so it fits beside them; when
      not even the last character does, the files and actions go in a
      message of their own. When ``measure("", actions)`` is over the limit
      the call fails ``TooLarge`` before posting.
    - ``on_part`` runs for every message created, uninterruptibly once its
      post returns; it has to be quick.
    - An empty input posts nothing, unless there are files or actions.

    A failure in the middle leaves the parts already posted in place; the
    error says what was posted and what was not.
    """

    @fx.gen
    def run():
        chat = yield from _chat.Chat()

        def failed(error: ChatError) -> ChatMarkdownError:
            return ChatMarkdownError(posted=(), remaining=markdown, cause=ChatCause(error))

        descriptor: Descriptor = yield from chat.descriptor(thread.platform).map_error(failed)
        if actions and descriptor.measure("", actions) > descriptor.limits.message_length:
            return (
                yield from fx.fail(
                    failed(
                        ChatError(
                            platform=thread.platform,
                            op="post",
                            reason=TooLarge(detail="actions_too_long"),
                        )
                    )
                )
            )
        settings: _Settings[Never, R] = _Settings(
            thread=thread,
            initial=markdown,
            descriptor=descriptor,
            chat=chat,
            reply_to=reply_to,
            max_parts=max_parts,
            overflow=overflow,
            min_write_interval=min_write_interval,
            on_part=on_part,
            files=files,
            actions=actions,
            unattached_note=unattached_note,
        )
        result: Result = yield from _Reply(settings).run()
        return result

    return run.with_span("ChatMarkdown.post", attributes={"chat.platform": thread.platform})


def stream[E = Never, RR = Never](
    thread: ChatThread,
    deltas: Stream[str, E, RR],
    *,
    recipient: str | None = None,
    reply_to: ReplyTo | None = None,
    max_parts: int | None = None,
    overflow: OverflowFile | None = None,
    min_write_interval: Duration | None = None,
    on_part: Callable[[Part], Effect[None, Never, RR]] | None = None,
) -> Effect[Result, ChatMarkdownError[E], _chat.Chat | Registry | RR]:
    """Writes a stream of Markdown deltas as one reply, as the text arrives.

    - With a ``recipient`` and an adapter with a native stream, the reply is
      written by native appends; otherwise, or when the first native start
      fails ``Unsupported``, it posts and then edits. On an adapter without
      ``edit`` each part is posted once, when it rolls over or the reply
      ends.
    - Text that outgrows a message rolls over at a block boundary, each new
      message counting against ``max_parts``. A native stream rolls over at
      the next boundary past 85% of ``limits.stream_length`` and rotates at
      80% of ``limits.stream_age``. Every append leaves room to close the
      code fence it ends in.
    - Writes are paced by ``min_write_interval`` on ``Clock``; each takes all
      the text that arrived meanwhile. An append holds back the unfinished
      last line, unless inside a code fence; an edit closes an open fence.
    - An intermediate edit that fails ``"retry"`` or ``"uncertain"`` is
      dropped, since the next carries the whole text; a ``"denied"`` one,
      and any failure of a post or a part's last edit, fails the reply. A
      native append failing ``"retry"`` is tried again after its
      ``retry_after``; three in a row, or one ``"uncertain"``, stop the
      stream and carry on by post-then-edit. ``TooLarge`` starts the next
      part with the chunk.
    - ``Result.stopped`` is true when a user clicked stop.
    - When the deltas fail or the call is interrupted, what was received is
      written out within a short timeout and left posted. A write in flight
      is waited for, not cut off; only the timeout cuts it off, and its text
      is then reported as ``uncertain``.

    There are no files or actions: post them after the result. To stop a
    reply, end ``deltas`` with ``interrupt_when`` or ``halt_when`` so a
    ``Result`` still comes back. Native writes go through the ``Registry``,
    so a layer wrapping ``Chat`` does not see them.
    """
    require_stream(deltas, "deltas")

    @fx.gen
    def run():
        chat = yield from _chat.Chat()
        registry = yield from Registry()
        adapter = yield from registry.get(thread.platform).map_error(
            lambda error: ChatMarkdownError[E](posted=(), remaining="", cause=ChatCause(error))
        )
        native = (
            adapter.native_stream if "nativeStream" in adapter.descriptor.capabilities else None
        )
        settings: _Settings[E, RR] = _Settings(
            thread=thread,
            initial="",
            deltas=deltas,
            descriptor=adapter.descriptor,
            chat=chat,
            native=native,
            recipient=recipient,
            reply_to=reply_to,
            max_parts=max_parts,
            overflow=overflow,
            min_write_interval=min_write_interval,
            on_part=on_part,
        )
        result: Result = yield from _Reply(settings).run()
        return result

    return run.with_span("ChatMarkdown.stream", attributes={"chat.platform": thread.platform})


__all__ = [
    "Cause",
    "ChatCause",
    "ChatMarkdownError",
    "OverflowCause",
    "OverflowFile",
    "Part",
    "Result",
    "UpstreamCause",
    "post",
    "stream",
]
