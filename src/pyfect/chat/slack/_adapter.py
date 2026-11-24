"""The Slack ``ChatAdapter``: posts, edits, files, history, the native stream,
users and command answers, over ``SlackWebApi``."""

from __future__ import annotations

import re
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, Never, cast
from urllib.parse import urlsplit

import pyfect as fx
from pyfect import clock as _clock
from pyfect import stream as _stream
from pyfect._core import Effect
from pyfect._json_text import parse as _parse_json
from pyfect._json_value import JsonValue
from pyfect.chat.chat_adapter import (
    AppendResult,
    Descriptor,
    Direction,
    File,
    Limits,
    Posted,
    ThreadInfo,
    User,
    retry_safe,
)
from pyfect.chat.chat_error import (
    FILE_REFUSED,
    INTERACTION_EXPIRED,
    AnyReason,
    ChatError,
    InvalidRequest,
    NotFound,
    TooLarge,
    Unknown,
    Unsupported,
)
from pyfect.chat.chat_interaction import Defer, Visibility
from pyfect.chat.chat_message import Attachment, ChatMessage, ReplyTo
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.chat_ui import Action
from pyfect.chat.slack import (
    _address,
    _errors,
    _escape,
    _interactions,
    _json,
    _length,
    _normalize,
    _text,
)
from pyfect.chat.slack._address import Parts
from pyfect.chat.slack._escape import Notify
from pyfect.chat.slack._options import CurrentPostOptions, SessionStatus
from pyfect.chat.slack.slack_web_api import SlackWebApiService
from pyfect.duration import Duration, millis, minutes, seconds
from pyfect.http import request as http_request
from pyfect.http.client import HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.option import Option, Some
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.result import Ok
from pyfect.stream import Stream
from pyfect.tracer._spans import annotate_current_span

type Gen[A] = Generator[Effect[Any, ChatError, Any], Any, A]

DESCRIPTOR = Descriptor(
    platform=_address.PLATFORM,
    capabilities=frozenset(
        {
            "edit",
            "delete",
            "fetchMessage",
            "history",
            "download",
            "files",
            "startThread",
            "getThread",
            "opener",
            "getUser",
            "nativeStream",
            "buttons",
            "selects",
            "modals",
            "modalErrors",
            "commands",
            "ephemeral",
        }
    ),
    measure=_length.measure,
    limits=Limits(
        message_length=_length.MESSAGE_LENGTH,
        files_per_message=10,
        upload_bytes=1024 * 1024 * 1024,
        min_write_interval=seconds(1),
        stream_length=_length.MESSAGE_LENGTH,
        stream_age=minutes(10),
        follow_up_age=minutes(30),
        actions_per_message=_interactions.ACTIONS_PER_MESSAGE,
        action_data_length=_interactions.ACTION_DATA_LENGTH,
        modal_metadata_length=_interactions.MODAL_METADATA_LENGTH,
        modal_fields=_interactions.MODAL_FIELDS,
    ),
)

_PAGE_SIZE = 200


def _is_slack_host(host: str) -> bool:
    """The hosts a command's ``response_url`` may point at. A deferral is
    data that may have crossed a queue, so the adapter posts only to Slack."""
    return host in ("slack.com", "slack-gov.com") or host.endswith((".slack.com", ".slack-gov.com"))


_SPENT_RESPONSE_URL = frozenset({"expired_url", "used_url"})
"""What a spent ``response_url`` answers, as plain text with a 404:
``used_url`` after five posts, ``expired_url`` after 30 minutes."""

_FILE_CALL_TIMEOUT = seconds(30)
"""The bound on each call of a file post from ``chat.postMessage`` on."""
_ATTACH_DEADLINE = minutes(1)
"""The bound on the whole attach, retries and waits included."""
_STREAM_UNSUPPORTED = frozenset(
    {
        "channel_type_not_supported",
        "feature_disabled",
        "not_allowed_token_type",
    }
)
"""Codes on ``chat.startStream`` that mean the feature is off for this thread."""
_EDIT_INTERVAL_MILLIS = 3_000
"""Floor between two edits to one message."""
_PACE_IDLE_MILLIS = 15 * 60 * 1000
"""How long a reply's backoff is kept after its last write."""
_TRAILING_HIGH_SURROGATE = re.compile("[\ud800-\udbff]$")


def response_type(visibility: Visibility) -> str:
    """The ``response_type`` of a command's answer."""
    return "ephemeral" if visibility == "ephemeral" else "in_channel"


def _well_formed(text: str) -> str:
    """``String.prototype.toWellFormed``: a lone surrogate becomes U+FFFD."""
    return re.sub("[\ud800-\udfff]", "�", text)


@dataclass
class _Backoff:
    """A reply's pace after a 429, shared by every message the reply writes."""

    interval_millis: float
    next_at: float
    last_write: float


@dataclass(frozen=True)
class _StreamState:
    escape: _escape.State
    # The Markdown the stream took, held tails left out.
    markdown: str
    # What its start and appends sent.
    sent: str
    stopped: bool = False
    # False while an append is in flight, and after one failed in a way the
    # layer repairs.
    settled: bool = True
    # Whether the cleanup edit has run or been skipped.
    cleaned: bool = False
    # Whether the session status at the end has been set.
    ended: bool = False


def _has_detail(code: str) -> Callable[[ChatError], bool]:
    return lambda error: error.reason.detail == code


def _user_name(user: _json.JsonObject) -> str:
    profile = _json.object_(user, "profile")
    return (
        _json.string(profile, "display_name")
        or _json.string(profile, "real_name")
        or _json.string(user, "real_name")
        or _json.string(user, "name")
        or _json.string(user, "id")
        or ""
    )


@dataclass(frozen=True, kw_only=True)
class SlackUser:
    """A Slack user from ``users.info``, with guest and Slack Connect status.
    ``is_stranger`` is a Slack Connect user from another organisation."""

    id: str
    team_id: str
    name: str
    is_bot: bool
    is_restricted: bool
    is_ultra_restricted: bool
    is_stranger: bool
    deleted: bool
    raw: JsonValue


type AttachFailed = Callable[[ChatThread, str, tuple[str, ...], AnyReason], object]
"""Builds the ``SlackAttachFailed`` cause, which lives in the public module."""


def _messages(answer: object) -> list[object]:
    obj = _json.as_object(answer)
    return [] if obj is None else _json.as_list(obj.get("messages"))


def _next_cursor(answer: object) -> str | None:
    return _json.string(_json.object_(answer, "response_metadata"), "next_cursor")


class SlackAdapter:
    """The adapter for one workspace (``slack_chat.layer`` builds it)."""

    def __init__(
        self,
        *,
        api: SlackWebApiService,
        http: HttpClientService[HttpClientError, Never],
        bot_token: Redacted[str],
        team_id: str,
        bot_user_id: Effect[str, ChatError],
        attach_failed: AttachFailed,
        max_retry_after: Duration | None = None,
    ) -> None:
        self._api = api
        self._http = http
        self._bot_token = bot_token
        self._team_id = team_id
        self._bot_user_id = bot_user_id
        self._attach_failed = attach_failed
        self._max_retry_after = max_retry_after
        self._streams: dict[str, _StreamState] = {}
        self._backoffs: dict[str, _Backoff] = {}
        self._next_edit: dict[str, float] = {}
        self._declared_agent = True

    @property
    def descriptor(self) -> Descriptor:
        """Slack's capabilities and limits."""
        return DESCRIPTOR

    @property
    def native_stream(self) -> SlackAdapter:
        """Slack's native streaming: ``chat.startStream`` and its kin."""
        return self

    # --- helpers ---------------------------------------------------------------------

    def _fail(self, op: str, reason: AnyReason) -> Effect[Never, ChatError]:
        return fx.fail(_errors.chat_error(op, reason))

    def _check_actions(self, op: str, actions: Sequence[Action]) -> Effect[None, ChatError]:
        """Refuses elements Slack would refuse, or that the adapter could not
        tell from a consumer's."""
        refusal = _interactions.check_actions(actions)
        return fx.void if refusal is None else self._fail(op, refusal)

    def _evict(self, now: float) -> None:
        if len(self._next_edit) >= 64:
            for key in [key for key, at in self._next_edit.items() if at <= now]:
                del self._next_edit[key]
        if len(self._backoffs) >= 64:
            idle = now - _PACE_IDLE_MILLIS
            for key in [key for key, b in self._backoffs.items() if b.last_write < idle]:
                del self._backoffs[key]

    def _paced[A](
        self, message_id: str, write: Effect[A, ChatError], kind: Literal["edit", "stream"]
    ) -> Effect[A, ChatError]:
        """The pace of the writes that grow one reply: stream appends, the
        starts of its later parts, and edits.

        - Edits to one message are at least 3 seconds apart.
        - After a 429, the next write waits for the retry-after, and each
          later write waits twice the interval it waited before, for the
          rest of the reply. The backoff is keyed by message and shared.
        - Each attempt reads the pace afresh.
        """

        def succeeded(_: object) -> Effect[None]:
            def mark(now: float) -> None:
                self._evict(now)
                backoff = self._backoffs.get(message_id)
                if backoff is not None:
                    backoff.next_at = now + backoff.interval_millis
                    backoff.last_write = now
                if kind == "edit":
                    self._next_edit[message_id] = now + _EDIT_INTERVAL_MILLIS

            return _clock.current_time_millis().map(mark)

        def failed(error: ChatError) -> Effect[None]:
            if error.reason._tag != "RateLimited":  # pyright: ignore[reportPrivateUsage]
                return fx.void

            def mark(now: float) -> None:
                self._evict(now)
                base = (
                    _EDIT_INTERVAL_MILLIS
                    if kind == "edit"
                    else DESCRIPTOR.limits.min_write_interval.to_millis()
                )
                backoff = self._backoffs.get(message_id) or _Backoff(base, now, now)
                backoff.interval_millis *= 2
                retry_after = error.retry_after
                backoff.next_at = now + (
                    backoff.interval_millis if retry_after is None else retry_after.to_millis()
                )
                backoff.last_write = now
                self._backoffs[message_id] = backoff

            return _clock.current_time_millis().map(mark)

        def run(now: float) -> Effect[A, ChatError]:
            backoff = self._backoffs.get(message_id)
            at = max(
                0 if backoff is None else backoff.next_at,
                self._next_edit.get(message_id, 0) if kind == "edit" else 0,
            )
            wait = at - now
            waited = _clock.sleep(millis(wait)) if wait > 0 else fx.void
            return waited.flat_map(lambda _: write.tap(succeeded).tap_error(failed))

        return _clock.current_time_millis().flat_map(run)

    def _call(
        self,
        op: str,
        method: str,
        body: Mapping[str, object],
        *,
        write: bool = False,
        retry: bool = True,
    ) -> Effect[Any, ChatError]:
        return self._api.call(method, body, write=write, retry=retry).map_error(
            lambda error: _errors.with_op(op, error)
        )

    def _resolve(self, op: str, thread: ChatThread) -> Effect[Parts, ChatError]:
        parts = _address.parts(thread)
        if parts is not None and parts.team == self._team_id:
            return fx.succeed(parts)
        return self._fail(op, InvalidRequest(detail="invalid_thread"))

    def _ts_of(
        self, op: str, write: bool, answer: object
    ) -> Effect[tuple[str, datetime], ChatError]:
        ts = _json.string(answer, "ts")
        sent = (
            None if ts is None or _normalize.TS.fullmatch(ts) is None else _normalize.timestamp(ts)
        )
        if ts is None or sent is None:
            return self._fail(op, _errors.invalid_response(write, "missing_ts"))
        return fx.succeed((ts, sent))

    def _check_sent(self, op: str, sent: str) -> Effect[None, ChatError]:
        """Refuses text past 12,000 code points as sent, which Slack would
        refuse with ``msg_too_long``. Slack's second count, with emoji as
        shortcodes, is left to Slack."""
        if len(sent) > _length.MESSAGE_LENGTH:
            return self._fail(op, TooLarge(subject="text", detail="msg_too_long"))
        return fx.void

    def _message_content(self, op: str, body: _text.Body) -> Effect[dict[str, object], ChatError]:
        """The body of a post or an update: the blocks and a ``text`` the
        adapter builds, cut to the call's budget. ``markdown_text`` is never
        used on these two calls, since Slack decides mentions from ``text``."""

        @fx.gen
        def run() -> Gen[dict[str, object]]:
            yield from self._check_sent(op, body.sent)
            if body.text == "" and not _text.has_actions(body):
                yield from self._fail(op, InvalidRequest(detail="no_text"))
            if body.dropped > 0:
                yield from annotate_current_span("slack.text.dropped_tokens", body.dropped)
            return {"blocks": list(body.blocks), "text": body.text}

        return run

    def _fetch_raw(self, op: str, channel: str, ts: str) -> Effect[object, ChatError]:
        """One message by ts, in or out of a thread, as Slack stores it."""

        def find(answer: object) -> Effect[object, ChatError]:
            found = next((m for m in _messages(answer) if _json.any_string(m, "ts") == ts), None)
            if found is None:
                return self._fail(op, NotFound(detail="message_not_found"))
            return fx.succeed(found)

        return self._call(
            op,
            "conversations.replies",
            {
                "channel": channel,
                "ts": ts,
                "latest": ts,
                "oldest": ts,
                "inclusive": True,
                "limit": 2,
            },
        ).flat_map(find)

    def _fetch_message(
        self, op: str, thread: ChatThread, message_id: str
    ) -> Effect[ChatMessage, ChatError]:
        @fx.gen
        def run() -> Gen[ChatMessage]:
            parts = yield from self._resolve(op, thread)
            bot_user_id = yield from self._bot_user_id
            raw = yield from self._fetch_raw(op, parts.channel, message_id)
            message = _normalize.message(
                raw, team=self._team_id, channel=parts.channel, bot_user_id=bot_user_id
            )
            if message is None:
                return (yield from self._fail(op, NotFound(detail="not_a_message")))
            return message

        return run

    def _session_status(self, channel: str, thread_ts: str, status: SessionStatus) -> Effect[None]:
        if not self._declared_agent:
            return fx.void

        def failed(error: ChatError) -> Effect[None]:
            if error.reason.detail == "not_authorized":
                self._declared_agent = False
            return fx.log_debug("agents.sessions.setStatus failed", error)

        return (
            self._call(
                "nativeStream.stop",
                "agents.sessions.setStatus",
                {"channel_id": channel, "thread_ts": thread_ts, "status": status},
                write=True,
                retry=False,
            )
            .as_void()
            .catch_all(failed)
        )

    # --- files -----------------------------------------------------------------------

    def _refused(self, error: ChatError) -> ChatError:
        """A ``denied`` failure of an upload call refused a file."""
        if error.reason.retry != "denied":
            return error
        return _errors.chat_error(error.op, _errors.file_refused(error.reason))

    def _stage(self, file: File) -> Effect[dict[str, str], ChatError]:
        @fx.gen
        def run() -> Gen[dict[str, str]]:
            answer = yield from self._call(
                "post",
                "files.getUploadURLExternal",
                {"filename": file.name, "length": len(file.content)},
            )
            upload_url = _json.string(answer, "upload_url")
            file_id = _json.string(answer, "file_id")
            if upload_url is None or file_id is None:
                yield from self._fail("post", _errors.invalid_response(False, "missing_upload_url"))
            # Staging posts nothing, so every failure here is safe to retry.
            response = yield from self._http.execute(
                http_request.post(cast("str", upload_url)).body_bytes(
                    file.content, file.content_type
                )
            ).map_error(
                lambda error: _errors.chat_error(
                    "post", _errors.transport(False, "upload_failed", error)
                )
            )
            if not 200 <= response.status < 300:
                yield from self._fail(
                    "post", _errors.reason_for_status(response.status, write=False)
                )
            return {"id": cast("str", file_id), "title": file.name}

        return run.map_error(self._refused)

    def _bounded[A](
        self, effect: Effect[A, ChatError], on_timeout: AnyReason
    ) -> Effect[A, ChatError]:
        """One call of the post, the attach or the rollback, cut off after
        30 seconds."""
        return effect.timeout_or_else(_FILE_CALL_TIMEOUT, lambda: self._fail("post", on_timeout))

    def _post_files(  # noqa: PLR0917
        self,
        thread: ChatThread,
        parts: Parts,
        markdown: str,
        files: Sequence[File],
        actions: Sequence[Action],
        notify: Notify,
        unfurl: bool,
    ) -> Effect[Posted, ChatError]:
        """Upload, post, then attach. The files are completed with no
        channel, so nothing is visible until ``chat.postMessage``, and
        ``chat.update`` with ``file_ids`` attaches them. Both calls send the
        same body, with ``text`` under the update budget.

        From the post on, the route runs uninterruptible, with a timeout on
        each call and a minute on the attach as a whole. When the attach
        still fails, the message is deleted and then the files, best effort.
        If the delete fails, the post fails ``Unknown`` with a
        ``SlackAttachFailed`` as its cause, and the files are kept."""
        limits = DESCRIPTOR.limits

        @fx.gen
        def run() -> Gen[Posted]:
            if len(files) > limits.files_per_message or any(
                len(file.content) > limits.upload_bytes for file in files
            ):
                yield from self._fail("post", TooLarge(subject="files", detail=FILE_REFUSED))
            content = _text.body(markdown, notify, _text.UPDATE_BUDGET)
            if content.text == "":
                content = _text.placeholder([file.name for file in files], _text.UPDATE_BUDGET)
            body = yield from self._message_content("post", _text.with_actions(content, actions))
            staged: list[dict[str, str]] = yield from fx.for_each(files, self._stage)
            yield from self._call(
                "post", "files.completeUploadExternal", {"files": staged}
            ).map_error(self._refused)
            file_ids = tuple(file["id"] for file in staged)
            return (
                yield from self._attach(thread, parts, body, file_ids, unfurl).uninterruptible()
            )

        return run

    def _attach(
        self,
        thread: ChatThread,
        parts: Parts,
        body: dict[str, object],
        file_ids: tuple[str, ...],
        unfurl: bool,
    ) -> Effect[Posted, ChatError]:
        channel = parts.channel
        remove_files = self._bounded(
            fx.for_each(
                file_ids,
                lambda file: self._call(
                    "post", "files.delete", {"file": file}, write=True
                ).ignore(),
                concurrency="unbounded",
                discard=True,
            ),
            _errors.transport(True, "timeout"),
        ).ignore()

        @fx.gen
        def run() -> Gen[Posted]:
            answer = yield from self._bounded(
                self._call(
                    "post",
                    "chat.postMessage",
                    {
                        "channel": channel,
                        "thread_ts": parts.thread_ts,
                        **body,
                        "unfurl_links": unfurl,
                        "unfurl_media": unfurl,
                    },
                    write=True,
                ),
                _errors.transport(True, "timeout"),
            ).tap_error(lambda _: remove_files)
            ts, sent = yield from self._ts_of("post", True, answer)
            posted = Posted(ts, thread, sent)
            attached = (
                yield from retry_safe(
                    self._paced(
                        ts,
                        self._bounded(
                            self._call(
                                "post",
                                "chat.update",
                                {"channel": channel, "ts": ts, **body, "file_ids": list(file_ids)},
                                retry=False,
                            ),
                            _errors.transport(False, "timeout"),
                        ),
                        "edit",
                    ),
                    max_retry_after=self._max_retry_after,
                )
                .timeout_or_else(
                    _ATTACH_DEADLINE,
                    lambda: self._fail("post", _errors.transport(False, "attach_deadline")),
                )
                .result()
            )
            if isinstance(attached, Ok):
                return posted
            error = attached.error
            yield from annotate_current_span("slack.attach.failed", error.reason._tag)  # pyright: ignore[reportPrivateUsage]
            deleted = yield from self._bounded(
                self._call("post", "chat.delete", {"channel": channel, "ts": ts}, write=True),
                _errors.transport(True, "timeout"),
            ).result()
            if isinstance(deleted, Ok):
                yield from remove_files
                return (yield from fx.fail(self._refused(error)))
            return (
                yield from self._fail(
                    "post",
                    Unknown(
                        detail="attach_failed_message_left",
                        cause=self._attach_failed(thread, ts, file_ids, error.reason),
                    ),
                )
            )

        return run

    # --- ops -------------------------------------------------------------------------

    def post(
        self,
        thread: ChatThread,
        *,
        markdown: str,
        reply_to: ReplyTo | None = None,
        files: Sequence[File] = (),
        actions: Sequence[Action] = (),
    ) -> Effect[Posted, ChatError]:
        """``chat.postMessage``: one ``markdown`` block, the elements' ``actions``
        block, and a ``text`` the adapter builds; with files, upload, post and
        attach."""

        @fx.gen
        def run() -> Gen[Posted]:
            parts = yield from self._resolve("post", thread)
            if reply_to is not None:
                yield from self._fail("post", Unsupported(capability="replyTo"))
            yield from self._check_actions("post", actions)
            options = yield from CurrentPostOptions()
            notify = options.notify
            unfurl = options.unfurl is True
            if files:
                return (
                    yield from self._post_files(
                        thread, parts, markdown, files, actions, notify, unfurl
                    )
                )
            body = yield from self._message_content(
                "post", _text.body(markdown, notify, _text.POST_BUDGET, actions)
            )
            answer = yield from self._call(
                "post",
                "chat.postMessage",
                {
                    "channel": parts.channel,
                    "thread_ts": parts.thread_ts,
                    **body,
                    "unfurl_links": unfurl,
                    "unfurl_media": unfurl,
                },
                write=True,
            )
            ts, sent = yield from self._ts_of("post", True, answer)
            return Posted(ts, thread, sent)

        return run

    def edit(
        self, thread: ChatThread, message_id: str, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]:
        """``chat.update``, paced, with ``text`` cut to 3,800 bytes."""

        @fx.gen
        def run() -> Gen[None]:
            parts = yield from self._resolve("edit", thread)
            yield from self._check_actions("edit", actions)
            options = yield from CurrentPostOptions()
            body = yield from self._message_content(
                "edit", _text.body(markdown, options.notify, _text.UPDATE_BUDGET, actions)
            )
            yield from retry_safe(
                self._paced(
                    message_id,
                    self._call(
                        "edit",
                        "chat.update",
                        {"channel": parts.channel, "ts": message_id, **body},
                        write=True,
                        retry=False,
                    ),
                    "edit",
                ),
                max_retry_after=self._max_retry_after,
            )

        return run

    def delete(self, thread: ChatThread, message_id: str) -> Effect[None, ChatError]:
        """``chat.delete``; an open stream is stopped first."""

        @fx.gen
        def run() -> Gen[None]:
            parts = yield from self._resolve("delete", thread)
            body = {"channel": parts.channel, "ts": message_id}

            def stop_then_delete(error: ChatError) -> Effect[Any, ChatError]:
                def deleted(_: object) -> Effect[Any, ChatError]:
                    self._streams.pop(message_id, None)
                    return self._call("delete", "chat.delete", body, write=True)

                return self._call(
                    "delete", "chat.stopStream", body, write=True, retry=False
                ).match_effect(on_failure=lambda _: fx.fail(error), on_success=deleted)

            yield from self._call("delete", "chat.delete", body, write=True).catch_if(
                _has_detail("cant_delete_message"), stop_then_delete
            )

        return run

    def fetch_message(self, thread: ChatThread, message_id: str) -> Effect[ChatMessage, ChatError]:
        """One message, through ``conversations.replies``."""
        return self._fetch_message("fetchMessage", thread, message_id)

    def history(
        self, thread: ChatThread, *, direction: Direction, from_: str | None = None
    ) -> Stream[ChatMessage, ChatError]:
        """``conversations.replies`` for a thread, oldest first, or
        ``conversations.history`` for a channel, newest first; the other
        direction reads every page and reverses."""

        @fx.gen
        def make() -> Generator[Effect[Any, ChatError, Any], Any, Stream[ChatMessage, ChatError]]:
            parts = yield from self._resolve("history", thread)
            bot_user_id = yield from self._bot_user_id

            def after(message: ChatMessage) -> bool:
                if from_ is None:
                    return True
                order = _address.compare_ts(message.id, from_)
                return order > 0 if direction == "forward" else order < 0

            def normalized(raw: Stream[object, ChatError]) -> Stream[ChatMessage, ChatError]:
                def one(message: object) -> list[ChatMessage]:
                    found = _normalize.message(
                        message, team=self._team_id, channel=parts.channel, bot_user_id=bot_user_id
                    )
                    return [found] if found is not None and after(found) else []

                return raw.flat_map(lambda message: _stream.from_iterable(one(message)))

            def reversed_(stream: Stream[ChatMessage, ChatError]) -> Stream[ChatMessage, ChatError]:
                return _stream.unwrap(
                    stream.run_collect().map(lambda all: _stream.from_iterable(all[::-1]))
                )

            bound: dict[str, object] = (
                {}
                if from_ is None
                else {"oldest": from_}
                if direction == "forward"
                else {"latest": from_}
            )

            def pages(
                method: str, body: dict[str, object], skip_opener: str | None
            ) -> Stream[object, ChatError]:
                def page(
                    cursor: str | None,
                ) -> Effect[tuple[list[object], Option[str | None]], ChatError]:
                    def read(answer: object) -> tuple[list[object], Option[str | None]]:
                        found = _messages(answer)
                        if skip_opener is not None and cursor is not None:
                            found = [m for m in found if _json.any_string(m, "ts") != skip_opener]
                        following = _next_cursor(answer)
                        return found, None if following is None else Some(following)

                    return self._call("history", method, {**body, "cursor": cursor}).map(read)

                return _stream.paginate(None, page)

            if parts.thread_ts is not None:
                # Oldest first, from the thread's start. Slack puts the opener on every page.
                replies = normalized(
                    pages(
                        "conversations.replies",
                        {
                            "channel": parts.channel,
                            "ts": parts.thread_ts,
                            "limit": _PAGE_SIZE,
                            **bound,
                        },
                        parts.thread_ts,
                    )
                )
                return replies if direction == "forward" else reversed_(replies)
            # Newest first. A reply broadcast to the channel is the thread's.
            channel = normalized(
                pages(
                    "conversations.history",
                    {"channel": parts.channel, "limit": _PAGE_SIZE, **bound},
                    None,
                )
            ).filter(lambda message: message.thread.id == thread.id)
            return channel if direction == "backward" else reversed_(channel)

        return _stream.unwrap(make)

    def download(
        self, thread: ChatThread, attachment: Attachment, *, max_bytes: int
    ) -> Stream[bytes, ChatError]:
        """``files.info`` then a GET of the private URL with the bot token,
        failing ``TooLarge`` as soon as more than ``max_bytes`` arrive."""
        op = "download"
        too_large = _errors.chat_error(op, TooLarge(subject="files", detail="max_bytes"))

        @fx.gen
        def make() -> Generator[Effect[Any, ChatError, Any], Any, Stream[bytes, ChatError]]:
            yield from self._resolve(op, thread)
            if attachment.size is not None and attachment.size > max_bytes:
                yield from fx.fail(too_large)
            answer = yield from self._call(op, "files.info", {"file": attachment.id})
            file = _json.object_(answer, "file")
            url = _json.string(file, "url_private_download") or _json.string(file, "url_private")
            if url is None:
                yield from self._fail(op, _errors.invalid_response(False, "missing_url"))
            response = yield from self._http.execute(
                http_request.get(cast("str", url)).bearer_token(redacted_value(self._bot_token))
            ).map_error(
                lambda error: _errors.chat_error(
                    op, _errors.transport(False, type(error.reason).__name__, error)
                )
            )
            if not 200 <= response.status < 300:
                yield from self._fail(op, _errors.reason_for_status(response.status, write=False))
            received = 0

            def counted(chunk: bytes) -> Effect[bytes, ChatError]:
                nonlocal received
                received += len(chunk)
                return fx.fail(too_large) if received > max_bytes else fx.succeed(chunk)

            return response.stream.map_error(
                lambda error: _errors.chat_error(
                    op, _errors.transport(False, type(error.reason).__name__, error)
                )
            ).map_effect(counted)

        return _stream.unwrap(make)

    def start_thread(
        self, thread: ChatThread, message_id: str, *, name: str | None = None
    ) -> Effect[ChatThread, ChatError]:
        """The thread under ``message_id``; a thread address is its own."""
        return self._resolve("startThread", thread).map(
            lambda parts: (
                _address.thread(Parts(parts.team, parts.channel, message_id))
                if parts.thread_ts is None
                else thread
            )
        )

    def get_thread(self, thread: ChatThread) -> Effect[ThreadInfo, ChatError]:
        """``conversations.info`` for the channel."""

        @fx.gen
        def run() -> Gen[ThreadInfo]:
            parts = yield from self._resolve("getThread", thread)
            answer = yield from self._call(
                "getThread", "conversations.info", {"channel": parts.channel}
            )
            channel = _json.object_(answer, "channel")
            if channel is None:
                return (
                    yield from self._fail(
                        "getThread", _errors.invalid_response(False, "missing_channel")
                    )
                )
            direct = channel.get("is_im") is True or channel.get("is_mpim") is True
            in_thread = parts.thread_ts is not None
            created = _json.number(channel, "created")
            created_at = (
                _normalize.timestamp(parts.thread_ts)
                if parts.thread_ts is not None
                else None
                if created is None
                else _normalize.from_seconds(created)
            )
            return ThreadInfo(
                thread=thread,
                kind="thread" if in_thread else "direct" if direct else "channel",
                name=None if in_thread or direct else _json.string(channel, "name"),
                topic=None if in_thread else _json.string(_json.object_(channel, "topic"), "value"),
                parent=_address.thread(Parts(parts.team, parts.channel)) if in_thread else None,
                created_at=created_at,
                raw=cast("JsonValue", channel),
            )

        return run

    def opener(self, thread: ChatThread) -> Effect[ChatMessage | None, ChatError]:
        """The thread's root message; ``None`` for a channel, or when the
        root is gone or is not a message."""

        @fx.gen
        def run() -> Gen[ChatMessage | None]:
            parts = yield from self._resolve("opener", thread)
            if parts.thread_ts is None:
                return None
            channel = _address.thread(Parts(parts.team, parts.channel))
            return (
                yield from self._fetch_message("opener", channel, parts.thread_ts).catch_if(
                    lambda error: error.reason._tag == "NotFound",  # pyright: ignore[reportPrivateUsage]
                    lambda _: fx.succeed(None),
                )
            )

        return run

    def user(self, id: str) -> Effect[SlackUser, ChatError]:
        """``users.info``, every time."""

        def read(answer: object) -> Effect[SlackUser, ChatError]:
            raw = _json.object_(answer, "user")
            user_id = _json.string(raw, "id")
            if raw is None or user_id is None:
                return self._fail("user", _errors.invalid_response(False, "missing_user"))
            team = _json.string(raw, "team_id") or self._team_id
            return fx.succeed(
                SlackUser(
                    id=user_id,
                    team_id=team,
                    name=_user_name(raw),
                    is_bot=raw.get("is_bot") is True,
                    is_restricted=raw.get("is_restricted") is True,
                    is_ultra_restricted=raw.get("is_ultra_restricted") is True,
                    is_stranger=raw.get("is_stranger") is True
                    or (team != self._team_id and "enterprise_user" not in raw),
                    deleted=raw.get("deleted") is True,
                    raw=cast("JsonValue", raw),
                )
            )

        return self._call("user", "users.info", {"user": id}).flat_map(read)

    def get_user(self, id: str, *, in_: ChatThread | None = None) -> Effect[User, ChatError]:
        """``users.info``; a ``bot_message`` author's bot id is ``NotFound``."""

        @fx.gen
        def run() -> Gen[User]:
            bot_user_id = yield from self._bot_user_id
            found = yield from self.user(id).map_error(
                lambda error: _errors.with_op("getUser", error)
            )
            return User(
                id=found.id,
                name=found.name,
                is_bot=found.is_bot,
                is_self=found.id == bot_user_id,
                raw=found.raw,
            )

        return run

    def answer(
        self, op: str, markdown: str, actions: Sequence[Action], visibility: Visibility
    ) -> Effect[Mapping[str, object], ChatError]:
        """The body of a command's answer, ``Respond`` or ``follow_up``: what
        a ``post`` of the same content sends with the default post options,
        after the same checks, with its ``response_type``. It notifies
        nobody and unfurls nothing."""

        @fx.gen
        def run() -> Gen[Mapping[str, object]]:
            yield from self._check_actions(op, actions)
            body = yield from self._message_content(
                op, _text.body(markdown, _escape.NOBODY, _text.POST_BUDGET, actions)
            )
            return {
                "response_type": response_type(visibility),
                **body,
                "unfurl_links": False,
                "unfurl_media": False,
            }

        return run

    def _response_url(self, op: str, deferred: Defer) -> Effect[str, ChatError]:
        value = _json.string(deferred.command.raw, "response_url")
        try:
            url = None if value is None else urlsplit(value)
            host = None if url is None else url.hostname
        except ValueError:
            url = host = None
        if url is not None and url.scheme == "https" and host is not None and _is_slack_host(host):
            return fx.succeed(cast("str", value))
        return self._fail(op, InvalidRequest(detail="invalid_response_url"))

    def follow_up(
        self, deferred: Defer, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]:
        """One POST to the command's ``response_url``, never retried. A spent
        URL is ``NotFound`` with detail ``interaction_expired``."""
        op = "followUp"

        @fx.gen
        def run() -> Gen[None]:
            url = yield from self._response_url(op, deferred)
            body = yield from self.answer(op, markdown, actions, deferred.visibility)
            response = yield from self._http.execute(
                http_request.post(url).body_json_unsafe(body)
            ).map_error(
                lambda error: _errors.chat_error(
                    op, _errors.transport(True, type(error.reason).__name__, error)
                )
            )
            if 200 <= response.status < 300:
                return None
            text = yield from response.text.or_else_succeed(lambda _: "")
            try:
                parsed: object = _parse_json(text)
                code = _json.string(parsed, "error")
            except ValueError:
                code = text.strip() or None
            if response.status in (404, 410) or (code is not None and code in _SPENT_RESPONSE_URL):
                yield from self._fail(op, NotFound(detail=INTERACTION_EXPIRED, cause=code))
            yield from self._fail(
                op, _errors.reason_for_status(response.status, write=True, cause=code)
            )

        return run

    # --- native stream ---------------------------------------------------------------

    def _cleanup_edit(
        self, op: str, channel: str, message_id: str, state: _StreamState, notify: Notify
    ) -> Effect[None]:
        """The cleanup edit: once a stream is closed, a message whose appends
        differ from what the block path would send is rewritten once as
        blocks plus ``text``, which takes out the zero-width spaces.

        It is skipped when the block would pass 12,000 and when the edit
        fails, saying so on the span. A message whose last append is
        unsettled is left to the layer's repair."""
        if _escape.escape(state.markdown, notify, flush=True).sent == state.sent:
            return fx.void
        if not state.settled:
            return annotate_current_span("slack.stream.cleanup", "unsettled")
        body = _text.body(state.markdown, notify, _text.UPDATE_BUDGET)
        if len(body.sent) > _length.MESSAGE_LENGTH:
            return annotate_current_span("slack.stream.cleanup", "too_long")

        @fx.gen
        def run() -> Generator[Effect[Any, Never, Any], Any]:
            if body.dropped > 0:
                yield from annotate_current_span("slack.text.dropped_tokens", body.dropped)
            edited = yield from self._paced(
                message_id,
                self._call(
                    op,
                    "chat.update",
                    {
                        "channel": channel,
                        "ts": message_id,
                        "blocks": list(body.blocks),
                        "text": body.text,
                    },
                    write=True,
                    retry=False,
                ),
                "edit",
            ).result()
            yield from annotate_current_span(
                "slack.stream.cleanup", "edited" if isinstance(edited, Ok) else "failed"
            )

        return run

    def _end_session(
        self, channel: str, thread_ts: str | None, message_id: str, status: SessionStatus
    ) -> Effect[None]:
        """Moves the agent session of a stopped stream off ``processing``,
        once. It is marked only after the call, so an interrupted one runs
        again on the stop the layer's finaliser sends."""

        def run() -> Effect[None]:
            state = self._streams.get(message_id)
            if thread_ts is None or (state is not None and state.ended):
                return fx.void

            def mark(_: None) -> None:
                current = self._streams.get(message_id)
                if current is not None:
                    self._streams[message_id] = replace(current, ended=True)

            return self._session_status(channel, thread_ts, status).map(mark)

        return fx.suspend(run)

    def _cleanup(self, op: str, channel: str, message_id: str, notify: Notify) -> Effect[None]:
        def run() -> Effect[None]:
            state = self._streams.get(message_id)
            if state is None or state.cleaned:
                return fx.void

            def mark(_: None) -> None:
                self._streams[message_id] = replace(state, cleaned=True)

            return self._cleanup_edit(op, channel, message_id, state, notify).map(mark)

        return fx.suspend(run)

    def start(
        self,
        thread: ChatThread,
        *,
        markdown: str,
        reply_to: ReplyTo | None = None,
        recipient: str | None = None,
        continues: str | None = None,
    ) -> Effect[Posted, ChatError]:
        """``chat.startStream`` in a thread, for a recipient; a later part of
        a reply goes at the reply's pace, and keeps it."""
        op = "nativeStream.start"

        @fx.gen
        def run() -> Gen[Posted]:
            options = yield from CurrentPostOptions()
            if options.native_stream is False:
                yield from self._fail(op, Unsupported(capability="nativeStream", detail="disabled"))
            parts = yield from self._resolve(op, thread)
            if parts.thread_ts is None or recipient is None or reply_to is not None:
                yield from self._fail(op, Unsupported(capability="nativeStream"))
            escaped = _escape.escape_stream(markdown, options.notify, flush=True)
            # Slack blanks a message whose surrogate pair is split across two appends.
            sent = _well_formed(escaped.sent)
            yield from self._check_sent(op, sent)

            def unsupported(error: ChatError) -> Effect[Never, ChatError]:
                return self._fail(
                    op,
                    Unsupported(capability="nativeStream", detail=error.reason.detail, cause=error),
                )

            start_call = self._call(
                op,
                "chat.startStream",
                {
                    "channel": parts.channel,
                    "thread_ts": parts.thread_ts,
                    "recipient_user_id": recipient,
                    "recipient_team_id": options.recipient_team_id or parts.team,
                    "markdown_text": sent or None,
                },
                write=True,
                retry=False,
            ).catch_if(lambda error: error.reason.detail in _STREAM_UNSUPPORTED, unsupported)
            answer = yield from (
                start_call if continues is None else self._paced(continues, start_call, "stream")
            )
            ts, created = yield from self._ts_of(op, True, answer)
            backoff = None if continues is None else self._backoffs.get(continues)
            if backoff is not None:
                self._backoffs[ts] = backoff
            self._streams[ts] = _StreamState(escaped.state, markdown, sent)
            return Posted(ts, thread, created)

        return run

    def append(
        self, thread: ChatThread, message_id: str, markdown: str, *, flush: bool = False
    ) -> Effect[AppendResult, ChatError]:
        """``chat.appendStream``, holding back what the next delta could
        still change."""
        op = "nativeStream.append"

        @fx.gen
        def run() -> Gen[AppendResult]:
            parts = yield from self._resolve(op, thread)
            options = yield from CurrentPostOptions()
            notify = options.notify
            state = self._streams.get(message_id) or _StreamState(_escape.INITIAL_STATE, "", "")
            # A trailing high surrogate waits for its other half.
            text = (
                markdown[:-1]
                if not flush and _TRAILING_HIGH_SURROGATE.search(markdown)
                else markdown
            )
            escaped = _escape.escape_stream(text, notify, state=state.escape, flush=flush)
            held = len(markdown) - escaped.consumed
            if escaped.sent == "":
                return AppendResult("open", held)
            sent = _well_formed(escaped.sent)
            yield from self._check_sent(op, state.sent + sent)

            def unsettle() -> None:
                self._streams[message_id] = replace(state, settled=False)

            def appended(_: object) -> AppendResult:
                self._streams[message_id] = _StreamState(
                    escaped.state,
                    state.markdown + text[: escaped.consumed],
                    state.sent + sent,
                )
                return AppendResult("open", held)

            def closed(_: ChatError) -> Effect[AppendResult]:
                # The layer carries on by editing the message, and sends no stop.
                self._streams.pop(message_id, None)
                return fx.succeed(AppendResult("closed", 0))

            def stopped(_: ChatError) -> Effect[AppendResult]:
                # Slack closed the stream and the reply ends stopped. The layer sends no
                # stop after this, so the cleanup and the session status go here.
                self._streams[message_id] = replace(state, stopped=True)
                return (
                    self._cleanup(op, parts.channel, message_id, notify)
                    .flat_map(
                        lambda _: self._end_session(
                            parts.channel,
                            parts.thread_ts,
                            message_id,
                            options.session_status_at_end or "active",
                        )
                    )
                    .as_(AppendResult("stopped", 0))
                )

            def restore(error: ChatError) -> Effect[None]:
                if error.retry == "denied":
                    self._streams[message_id] = state
                return fx.void

            return (
                yield from self._paced(
                    message_id,
                    fx.sync(unsettle).flat_map(
                        lambda _: self._call(
                            op,
                            "chat.appendStream",
                            {"channel": parts.channel, "ts": message_id, "markdown_text": sent},
                            write=True,
                            retry=False,
                        )
                    ),
                    "stream",
                )
                .map(appended)
                .catch_if(_has_detail("message_not_in_streaming_state"), closed)
                .catch_if(_has_detail("stopped_by_user"), stopped)
                .tap_error(restore)
            )

        return run

    def stop(
        self, thread: ChatThread, message_id: str, *, end: Literal["done", "rotating"]
    ) -> Effect[bool, ChatError]:
        """``chat.stopStream``, then the cleanup edit and, for a stream a user
        stopped, the session status."""
        op = "nativeStream.stop"

        @fx.gen
        def run() -> Gen[bool]:
            parts = yield from self._resolve(op, thread)
            options = yield from CurrentPostOptions()
            state = self._streams.get(message_id)
            # A rotating stop keeps the reply's backoff for its next part.
            backoff = self._backoffs.get(message_id)
            if backoff is not None and end == "done":
                for key in [key for key, value in self._backoffs.items() if value is backoff]:
                    del self._backoffs[key]
            status = "processing" if end == "rotating" else options.session_status_at_end
            body: dict[str, object] = {"channel": parts.channel, "ts": message_id}

            def plain() -> Effect[Any, ChatError]:
                return self._call(op, "chat.stopStream", body, write=True, retry=False)

            def undeclared(_: ChatError) -> Effect[Any, ChatError]:
                self._declared_agent = False
                return plain()

            stop = (
                plain()
                if status is None or not self._declared_agent
                else self._call(
                    op,
                    "chat.stopStream",
                    {**body, "session_status": status},
                    write=True,
                    retry=False,
                ).catch_if(_has_detail("not_authorized"), undeclared)
            )
            answer = yield from stop.catch_if(
                _has_detail("message_not_in_streaming_state"), lambda _: fx.succeed(None)
            )
            ai_context = _json.object_(_json.object_(answer, "message"), "ai_context")
            stopped = (
                (state is not None and state.stopped)
                or _json.string(answer, "result_status") == "stopped_by_user"
                or _json.string(ai_context, "result_status") == "stopped_by_user"
            )
            # Remember stopped_by_user across interruptions.
            current = self._streams.get(message_id)
            if stopped and current is not None:
                self._streams[message_id] = replace(current, stopped=True)
            yield from self._cleanup(op, parts.channel, message_id, options.notify)
            if stopped and end == "done":
                yield from self._end_session(
                    parts.channel,
                    parts.thread_ts,
                    message_id,
                    options.session_status_at_end or "active",
                )
            # Retain stream state until cleanup and session completion finish.
            self._streams.pop(message_id, None)
            return stopped

        return run


__all__ = ["DESCRIPTOR", "SlackAdapter", "SlackUser", "response_type"]
