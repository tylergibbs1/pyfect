"""The Telegram ``ChatAdapter`` (Effect's ``internal/adapter.ts``): rich
messages through ``sendRichMessage``, edits, deletes, downloads, chats and
members, and the public answer to a command."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from typing import Any, Literal, Never

import pyfect as fx
from pyfect import clock as _clock
from pyfect import date_time as _date_time
from pyfect._core import Effect
from pyfect._json_text import Json
from pyfect.chat.chat_adapter import (
    Descriptor,
    File,
    Limits,
    NativeStream,
    Posted,
    ThreadInfo,
    User,
    check_message_length,
)
from pyfect.chat.chat_error import INTERACTION_EXPIRED, Capability, ChatError, InvalidRequest
from pyfect.chat.chat_interaction import Defer
from pyfect.chat.chat_message import Attachment, ChatMessage, ReplyTo
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.chat_ui import Action, Select
from pyfect.chat.telegram import _actions, _address, _errors, _markdown
from pyfect.chat.telegram._address import Parts
from pyfect.chat.telegram._json import integer, object_, string
from pyfect.chat.telegram._normalize import display_name, full_name, raw, timestamp
from pyfect.chat.telegram._options import CurrentPostOptions, TelegramPostOptions
from pyfect.chat.telegram._receive import Origin, origin_of
from pyfect.chat.telegram.telegram_bot_api import TelegramBotApiService, Upload
from pyfect.duration import seconds
from pyfect.stream import Stream
from pyfect.stream import _constructors as _stream

type Gen[A] = Generator[Effect[Any, ChatError, Any], Any, A]

BASE_CAPABILITIES: frozenset[Capability] = frozenset(
    {"edit", "delete", "replyTo", "download", "getThread", "getUser"}
)

FOLLOW_UP_AGE = seconds(15)
"""How long Telegram takes an answer to a command, from the command's
``date``."""

DOWNLOAD_LIMIT = 20 * 1024 * 1024
"""The largest file the cloud Bot API server hands out."""

UPLOAD_BYTES = 50 * 1024 * 1024


def capabilities_of(*, files: bool, buttons: bool, commands: bool) -> frozenset[Capability]:
    """The base capabilities and the unverified ones turned on."""
    extra: set[Capability] = set()
    if files:
        extra.add("files")
    if buttons:
        extra.add("buttons")
    if commands:
        extra.add("commands")
    return BASE_CAPABILITIES | extra


def _measure(markdown: str, _actions: Sequence[Action] = ()) -> int:
    return _markdown.measure(markdown)


def descriptor_of(capabilities: frozenset[Capability]) -> Descriptor:
    buttons = "buttons" in capabilities
    return Descriptor(
        platform=_address.PLATFORM,
        capabilities=capabilities,
        measure=_measure,
        limits=Limits(
            message_length=_markdown.MESSAGE_LENGTH,
            files_per_message=_markdown.FILES_PER_MESSAGE if "files" in capabilities else 0,
            upload_bytes=UPLOAD_BYTES,
            min_write_interval=seconds(3),
            actions_per_message=_actions.ACTIONS_PER_MESSAGE if buttons else None,
            action_data_length=_actions.ACTION_DATA_LENGTH if buttons else None,
            follow_up_age=FOLLOW_UP_AGE if "commands" in capabilities else None,
        ),
    )


def _target(parts: Parts) -> dict[str, object]:
    target: dict[str, object] = {"chat_id": int(parts.chat_id)}
    if parts.message_thread_id is not None:
        target["message_thread_id"] = int(parts.message_thread_id)
    return target


class TelegramAdapter:
    """The Telegram adapter, for one bot."""

    def __init__(self, *, api: TelegramBotApiService, capabilities: frozenset[Capability]) -> None:
        self._api = api
        self._capabilities = capabilities
        self._descriptor = descriptor_of(capabilities)

    @property
    def descriptor(self) -> Descriptor:
        return self._descriptor

    @property
    def native_stream(self) -> NativeStream | None:
        return None

    def _fail(self, op: str, reason: _errors.AnyReason) -> Effect[Never, ChatError]:
        return fx.fail(_errors.chat_error(op, reason))

    def _unsupported(self, op: str, capability: Capability) -> Effect[Never, ChatError]:
        return self._fail(op, _errors.unsupported(capability))

    def _resolve(self, op: str, thread: ChatThread) -> Effect[Parts, ChatError]:
        parts = _address.parts(thread)
        if parts is None:
            return self._fail(op, _errors.invalid_request("invalid_thread"))
        return fx.succeed(parts)

    def _message_id(self, op: str, id: str) -> Effect[int, ChatError]:
        """A message id Telegram can act on, or ``NotFound`` without a call:
        a private answer's label reaches nothing."""
        n = _address.numeric_id(id)
        return (
            self._fail(op, _errors.not_found("message_not_found")) if n is None else fx.succeed(n)
        )

    def _markup(
        self, op: str, actions: Sequence[Action]
    ) -> Effect[_actions.Keyboard | None, ChatError]:
        if not actions:
            return fx.succeed(None)
        if any(isinstance(action, Select) for action in actions):
            return self._unsupported(op, "selects")
        if "buttons" not in self._capabilities:
            return self._unsupported(op, "buttons")
        keyboard = _actions.keyboard(actions)
        if isinstance(keyboard, _actions.Keyboard):
            return fx.succeed(keyboard)
        return self._fail(op, keyboard)

    def _check_files(self, op: str, files: Sequence[File]) -> Effect[None, ChatError]:
        if not files:
            return fx.void
        if "files" not in self._capabilities:
            return self._unsupported(op, "files")
        limits = self._descriptor.limits
        refused = len(files) > limits.files_per_message or any(
            len(file.content) > limits.upload_bytes for file in files
        )
        return self._fail(op, _errors.REFUSED_FILE) if refused else fx.void

    def _rich_message(
        self, markdown: str, files: int, options: TelegramPostOptions
    ) -> dict[str, object]:
        message: dict[str, object] = {
            "markdown": _markdown.render(
                markdown, mentions=frozenset(options.notify_users or ()), files=files
            ),
            "skip_entity_detection": True,
        }
        if files:
            message["media"] = [
                {"id": f"f{n}", "media": {"type": "document", "media": f"attach://f{n}"}}
                for n in range(1, files + 1)
            ]
        return message

    def _posted(self, op: str, thread: ChatThread, answer: Json) -> Effect[Posted, ChatError]:
        id = integer(answer, "message_id")
        date = integer(answer, "date")
        if id is None or id == 0:
            return self._fail(op, _errors.invalid_response(True, "missing_message_id"))
        when = None if date is None else timestamp(date)
        if when is None:
            return _date_time.now().map(
                lambda now: Posted(id=str(id), thread=thread, timestamp=now)
            )
        return fx.succeed(Posted(id=str(id), thread=thread, timestamp=when))

    def _send(
        self,
        op: str,
        thread: ChatThread,
        *,
        markdown: str,
        actions: Sequence[Action] = (),
        files: Sequence[File] = (),
        reply_to: int | None = None,
        retry: bool = True,
    ) -> Effect[Posted, ChatError]:
        """One ``sendRichMessage``. ``retry`` is false for answers, which are
        never retried."""

        @fx.gen
        def run() -> Gen[Posted]:
            parts: Parts = yield from self._resolve(op, thread)
            markup = yield from self._markup(op, actions)
            yield from self._check_files(op, files)
            yield from check_message_length(self._descriptor, op, markdown, actions)
            if _markdown.js_trim(markdown) == "" and not files:
                yield from self._fail(op, _errors.invalid_request("empty_message"))
            options: TelegramPostOptions = yield from CurrentPostOptions()
            params: dict[str, object] = {
                **_target(parts),
                "rich_message": self._rich_message(markdown, len(files), options),
            }
            if reply_to is not None:
                params["reply_parameters"] = {
                    "message_id": reply_to,
                    "allow_sending_without_reply": False,
                }
            if markup is not None:
                params["reply_markup"] = markup.json()
            if options.silent is True:
                params["disable_notification"] = True
            answer: Json = yield from self._api.call(
                "sendRichMessage",
                params,
                write=True,
                retry=retry,
                files=[Upload(f"f{n}", file) for n, file in enumerate(files, 1)],
            ).map_error(_errors.with_op(op))
            return (yield from self._posted(op, thread, answer))

        return run

    def post(
        self,
        thread: ChatThread,
        *,
        markdown: str,
        reply_to: ReplyTo | None = None,
        files: Sequence[File] = (),
        actions: Sequence[Action] = (),
    ) -> Effect[Posted, ChatError]:
        op = "post"
        if reply_to is None:
            return self._send(op, thread, markdown=markdown, actions=actions, files=files)
        return self._message_id(op, reply_to.message_id).flat_map(
            lambda id: self._send(
                op, thread, markdown=markdown, actions=actions, files=files, reply_to=id
            )
        )

    def edit(
        self, thread: ChatThread, message_id: str, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]:
        op = "edit"

        @fx.gen
        def run() -> Gen[None]:
            parts: Parts = yield from self._resolve(op, thread)
            message: int = yield from self._message_id(op, message_id)
            markup = yield from self._markup(op, actions)
            yield from check_message_length(self._descriptor, op, markdown, actions)
            if _markdown.js_trim(markdown) == "":
                yield from self._fail(op, _errors.invalid_request("empty_message"))
            options: TelegramPostOptions = yield from CurrentPostOptions()
            # An edit replaces the whole message: no actions removes the keyboard.
            params: dict[str, object] = {
                "chat_id": int(parts.chat_id),
                "message_id": message,
                "rich_message": self._rich_message(markdown, 0, options),
                "reply_markup": {"inline_keyboard": []} if markup is None else markup.json(),
            }

            def unmodified(error: ChatError) -> Effect[None, ChatError]:
                reason = error.reason
                if isinstance(reason, InvalidRequest) and reason.detail == "not_modified":
                    return fx.void
                return fx.fail(_errors.chat_error(op, reason))

            yield from (
                self._api.call("editMessageText", params, write=True)
                .as_void()
                .catch_all(unmodified)
            )

        return run

    def delete(self, thread: ChatThread, message_id: str) -> Effect[None, ChatError]:
        op = "delete"

        @fx.gen
        def run() -> Gen[None]:
            parts: Parts = yield from self._resolve(op, thread)
            message: int = yield from self._message_id(op, message_id)
            yield from self._api.call(
                "deleteMessage", {"chat_id": int(parts.chat_id), "message_id": message}, write=True
            ).map_error(_errors.with_op(op))

        return run

    def fetch_message(self, thread: ChatThread, message_id: str) -> Effect[ChatMessage, ChatError]:
        return self._unsupported("fetchMessage", "fetchMessage")

    def history(
        self,
        thread: ChatThread,
        *,
        direction: Literal["backward", "forward"],
        from_: str | None = None,
    ) -> Stream[ChatMessage, ChatError]:
        return _stream.fail(_errors.chat_error("history", _errors.unsupported("history")))

    def download(
        self, thread: ChatThread, attachment: Attachment, *, max_bytes: int
    ) -> Stream[bytes, ChatError]:
        op = "download"
        limit = min(max_bytes, DOWNLOAD_LIMIT)
        too_large = _errors.too_large("files", "max_bytes")

        @fx.gen
        def make() -> Gen[Stream[bytes, ChatError]]:
            yield from self._resolve(op, thread)
            if attachment.size is not None and attachment.size > limit:
                yield from self._fail(op, too_large)
            answer: Json = yield from self._api.call(
                "getFile", {"file_id": attachment.id}
            ).map_error(_errors.with_op(op))
            path = string(answer, "file_path")
            size = integer(answer, "file_size")
            if size is not None and size > limit:
                yield from self._fail(op, too_large)
            if path is None:
                return (
                    yield from self._fail(op, _errors.invalid_response(False, "missing_file_path"))
                )
            return self._api.file(path, max_bytes=limit)

        return _stream.unwrap(make)

    def start_thread(
        self, thread: ChatThread, message_id: str, *, name: str | None = None
    ) -> Effect[ChatThread, ChatError]:
        return self._unsupported("startThread", "startThread")

    def get_thread(self, thread: ChatThread) -> Effect[ThreadInfo, ChatError]:
        op = "getThread"

        @fx.gen
        def run() -> Gen[ThreadInfo]:
            parts: Parts = yield from self._resolve(op, thread)
            answer: Json = yield from self._api.call(
                "getChat", {"chat_id": int(parts.chat_id)}
            ).map_error(_errors.with_op(op))
            if parts.message_thread_id is not None:
                return ThreadInfo(
                    thread=thread,
                    kind="thread",
                    parent=_address.thread(parts.chat_id),
                    raw=raw(answer),
                )
            title = string(answer, "title")
            return ThreadInfo(
                thread=thread,
                kind="direct" if string(answer, "type") == "private" else "channel",
                name=title if title is not None else full_name(answer) or None,
                topic=string(answer, "description"),
                raw=raw(answer),
            )

        return run

    def opener(self, thread: ChatThread) -> Effect[ChatMessage | None, ChatError]:
        return self._unsupported("opener", "opener")

    def get_user(self, id: str, *, in_: ChatThread | None = None) -> Effect[User, ChatError]:
        op = "getUser"
        if in_ is None:
            return self._fail(op, _errors.invalid_request("in_required"))
        where: ChatThread = in_

        @fx.gen
        def run() -> Gen[User]:
            parts: Parts = yield from self._resolve(op, where)
            user_id = _address.numeric_id(id)
            if user_id is None:
                return (yield from self._fail(op, _errors.not_found("user_not_found")))
            answer: Json = yield from self._api.call(
                "getChatMember", {"chat_id": int(parts.chat_id), "user_id": user_id}
            ).map_error(_errors.with_op(op))
            user = object_(answer, "user")
            if user is None or str(integer(user, "id")) != id:
                return (yield from self._fail(op, _errors.invalid_response(False, "missing_user")))
            return User(
                id=id,
                name=display_name(user) or id,
                is_bot=user.get("is_bot") is True,
                is_self=id == self._api.bot_id,
                raw=raw(answer),
            )

        return run

    def answer(
        self, op: str, origin: Origin, markdown: str, actions: Sequence[Action]
    ) -> Effect[Posted, ChatError]:
        """A public answer to a command. Never retried, so a timeout can't
        post it twice, and outside any scoped post options."""
        return self._send(
            op,
            origin.thread,
            markdown=markdown,
            actions=actions,
            reply_to=origin.reply_to,
            retry=False,
        ).pipe(fx.provide_service(CurrentPostOptions, TelegramPostOptions()))

    def follow_up(
        self, deferred: Defer, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]:
        op = "followUp"
        if "commands" not in self._capabilities:
            return self._unsupported(op, "commands")
        if deferred.visibility == "ephemeral":
            return self._fail(op, _errors.PRIVATE_ANSWER)
        origin = origin_of(deferred.command)
        if origin is None:
            return self._fail(op, _errors.invalid_request("invalid_command"))
        found: Origin = origin
        deadline = (found.date + 1) * 1000 + FOLLOW_UP_AGE.to_millis()

        def answered(now: float) -> Effect[None, ChatError]:
            if now > deadline:
                return self._fail(op, _errors.not_found(INTERACTION_EXPIRED))
            return self.answer(op, found, markdown, actions).as_void()

        return _clock.current_time_millis().flat_map(answered)
