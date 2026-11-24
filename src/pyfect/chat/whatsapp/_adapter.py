"""The WhatsApp adapter for one business phone number (``whatsapp_chat.layer``
builds it)."""

from __future__ import annotations

from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Never
from urllib.parse import quote

import pyfect as fx
from pyfect import date_time as _date_time
from pyfect._core import Effect
from pyfect._js import to_well_formed
from pyfect._json_text import Json
from pyfect._json_value import JsonValue
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
from pyfect.chat.chat_error import (
    FILE_REFUSED,
    AnyReason,
    Capability,
    ChatError,
    InvalidRequest,
    TooLarge,
    Unsupported,
)
from pyfect.chat.chat_message import Attachment, ChatMessage, ReplyTo
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.chat_ui import Action
from pyfect.chat.whatsapp import _actions, _address, _errors, _json, _text
from pyfect.chat.whatsapp._options import CurrentPostOptions
from pyfect.chat.whatsapp.whatsapp_graph_api import WhatsAppGraphApiService
from pyfect.duration import seconds
from pyfect.http import body as http_body
from pyfect.http import request as http_request
from pyfect.http.client import HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.stream import Stream
from pyfect.stream import _constructors as _stream

if TYPE_CHECKING:
    from pyfect.chat.chat_interaction import Defer

type Gen[A] = Generator[Effect[Any, ChatError, Any], Any, A]


def _measure(markdown: str, actions: Sequence[Action] = ()) -> int:
    return _text.measure(markdown) + _actions.measure(actions)


DESCRIPTOR = Descriptor(
    platform=_address.PLATFORM,
    capabilities=frozenset(
        {"replyTo", "files", "download", "getThread", "opener", "buttons", "selects"}
    ),
    measure=_measure,
    limits=Limits(
        message_length=_text.MESSAGE_LENGTH,
        files_per_message=1,
        upload_bytes=100 * 1024 * 1024,
        min_write_interval=seconds(6),
        actions_per_message=_actions.ACTIONS_PER_MESSAGE,
        action_data_length=_actions.ACTION_DATA_LENGTH,
    ),
)

type MediaType = Literal["image", "video", "audio", "document"]


@dataclass(frozen=True)
class _Media:
    type: MediaType
    max_bytes: int


_MIB = 1024 * 1024
_IMAGE = _Media("image", 5 * _MIB)
_VIDEO = _Media("video", 16 * _MIB)
_AUDIO = _Media("audio", 16 * _MIB)
_DOCUMENT = _Media("document", 100 * _MIB)

_MEDIA_TYPES: Mapping[str, _Media] = {
    "image/jpeg": _IMAGE,
    "image/png": _IMAGE,
    "video/mp4": _VIDEO,
    "video/3gpp": _VIDEO,
    "audio/aac": _AUDIO,
    "audio/amr": _AUDIO,
    "audio/mpeg": _AUDIO,
    "audio/mp4": _AUDIO,
    "audio/ogg": _AUDIO,
    "text/plain": _DOCUMENT,
    "application/pdf": _DOCUMENT,
    "application/msword": _DOCUMENT,
    "application/vnd.ms-excel": _DOCUMENT,
    "application/vnd.ms-powerpoint": _DOCUMENT,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _DOCUMENT,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": _DOCUMENT,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": _DOCUMENT,
}
"""Meta's supported media, by MIME type, with the largest upload of each."""


def upload_type(content_type: str) -> str:
    """The MIME type a file is uploaded as: without parameters, and
    ``text/markdown`` as ``text/plain``."""
    base = _text.js_trim(content_type.split(";", maxsplit=1)[0]).lower()
    return "text/plain" if base == "text/markdown" else base


_REFUSED = TooLarge(subject="files", detail=FILE_REFUSED)


@dataclass(frozen=True)
class Template:
    """A template message: its approved name, its language code, such as
    ``en_US``, and Meta's ``components`` for its parameters, sent as they
    are."""

    name: str
    language: str
    components: Sequence[JsonValue] | None = None


@dataclass(frozen=True)
class _Checked:
    file: File
    mime: str
    type: MediaType


class WhatsAppAdapter:
    """The adapter for one business phone number."""

    def __init__(
        self,
        *,
        graph: WhatsAppGraphApiService,
        http: HttpClientService[HttpClientError, Never],
        access_token: Redacted[str],
        phone_number_id: str,
        messaging_account_id: str | None = None,
    ) -> None:
        self._graph = graph
        self._http = http
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        self._account: dict[str, object] = (
            {} if messaging_account_id is None else {"messaging_account_id": messaging_account_id}
        )

    @property
    def descriptor(self) -> Descriptor:
        """WhatsApp's capabilities and limits."""
        return DESCRIPTOR

    @property
    def native_stream(self) -> NativeStream | None:
        """WhatsApp has no edit, so no native stream."""
        return None

    # --- helpers ---------------------------------------------------------------------

    def _fail(self, op: str, reason: AnyReason) -> Effect[Never, ChatError]:
        return fx.fail(_errors.chat_error(op, reason))

    def _unsupported(self, op: str, capability: Capability) -> Effect[Never, ChatError]:
        return self._fail(op, Unsupported(capability=capability))

    def _resolve(self, op: str, thread: ChatThread) -> Effect[str, ChatError]:
        """The user of a thread this adapter can write to."""
        parts = _address.parts(thread)
        if parts is None:
            return self._fail(op, InvalidRequest(detail="invalid_thread"))
        if parts.kind == "group":
            return self._fail(op, InvalidRequest(detail="group_unsupported"))
        if parts.phone_number_id != self._phone_number_id:
            return self._fail(op, InvalidRequest(detail="other_phone_number"))
        return fx.succeed(parts.id)

    def _messages_path(self) -> str:
        return f"{self._phone_number_id}/messages"

    def _send(
        self, op: str, thread: ChatThread, user: str, message: Mapping[str, object]
    ) -> Effect[Posted, ChatError]:

        @fx.gen
        def run() -> Gen[Posted]:
            recipient = {"recipient": user} if _address.is_bsuid(user) else {"to": user}
            body = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                **self._account,
                **recipient,
                **message,
            }
            answer: Json = yield from self._graph.call(
                self._messages_path(), body=body, write=True
            ).map_error(lambda error: _errors.chat_error(op, error.reason))
            obj = _json.as_object(answer)
            messages = _json.as_list(None if obj is None else obj.get("messages"))
            id = _json.string(messages[0], "id") if messages else None
            if id is None:
                return (
                    yield from self._fail(op, _errors.invalid_response(True, "missing_message_id"))
                )
            timestamp: datetime = yield from _date_time.now()
            return Posted(id, thread, timestamp)

        return run

    def _check_file(
        self, files: Sequence[File], caption: str, plan: _actions.Plan
    ) -> AnyReason | _Checked:
        """The checks on a file, before anything is sent: its media type, or
        the refusal."""
        if len(files) > 1:
            return _REFUSED
        file = files[0]
        mime = upload_type(file.content_type)
        media = _MEDIA_TYPES.get(mime)
        if media is None or len(file.content) > media.max_bytes:
            return _REFUSED
        if plan.kind == "list":
            return _REFUSED
        if media.type == "audio" and (_text.js_trim(caption) != "" or plan.kind != "none"):
            return _REFUSED
        if _text.utf16_length(caption) > _text.SHORT_BODY_LENGTH:
            return _REFUSED
        return _Checked(file, mime, media.type)

    def _upload(self, op: str, file: File, mime: str) -> Effect[str, ChatError]:
        form = (
            http_body.FormData()
            .append("messaging_product", "whatsapp")
            .append("type", mime)
            .append("file", http_body.File(content=file.content, name=file.name, content_type=mime))
        )

        def refused(error: ChatError) -> ChatError:
            # Meta refusing the file itself is a file refusal: nothing was sent, so the text
            # can go without it.
            reason = error.reason
            if isinstance(reason, (TooLarge, InvalidRequest)):
                return _errors.chat_error(
                    op, TooLarge(subject="files", detail=FILE_REFUSED, cause=reason)
                )
            return _errors.chat_error(op, reason)

        def media_id(answer: Json) -> Effect[str, ChatError]:
            id = _json.string(answer, "id")
            if id is None:
                return self._fail(op, _errors.invalid_response(False, "missing_media_id"))
            return fx.succeed(id)

        return (
            self._graph.call(f"{self._phone_number_id}/media", form=form)
            .map_error(refused)
            .flat_map(media_id)
        )

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
        """One send; every check runs before any upload or send."""
        op = "post"

        @fx.gen
        def run() -> Gen[Posted]:
            user: str = yield from self._resolve(op, thread)
            options = yield from CurrentPostOptions()
            plan = _actions.plan(actions, options)
            if not isinstance(plan, _actions.Plan):
                return (yield from self._fail(op, plan))
            yield from check_message_length(DESCRIPTOR, op, markdown, actions)
            text = _actions.body(_text.render(markdown), actions)
            context: dict[str, object] = (
                {} if reply_to is None else {"context": {"message_id": reply_to.message_id}}
            )
            header: dict[str, object] | None = None
            if files:
                checked = self._check_file(files, text, plan)
                if not isinstance(checked, _Checked):
                    return (yield from self._fail(op, checked))
                media_id: str = yield from self._upload(op, checked.file, checked.mime)
                media: dict[str, object] = (
                    {"id": media_id, "filename": checked.file.name}
                    if checked.type == "document"
                    else {"id": media_id}
                )
                if plan.interactive is None:
                    caption = (
                        {}
                        if checked.type == "audio" or _text.js_trim(text) == ""
                        else {"caption": text}
                    )
                    return (
                        yield from self._send(
                            op,
                            thread,
                            user,
                            {**context, "type": checked.type, checked.type: {**media, **caption}},
                        )
                    )
                header = {"type": checked.type, checked.type: media}
            if plan.interactive is not None:
                interactive: dict[str, object] = {
                    "type": plan.interactive.type,
                    **({} if header is None else {"header": header}),
                    "body": {"text": text},
                    "action": plan.interactive.action,
                }
                return (
                    yield from self._send(
                        op,
                        thread,
                        user,
                        {**context, "type": "interactive", "interactive": interactive},
                    )
                )
            if _text.js_trim(text) == "":
                return (yield from self._fail(op, InvalidRequest(detail="empty_message")))
            return (
                yield from self._send(
                    op,
                    thread,
                    user,
                    {
                        **context,
                        "type": "text",
                        "text": {"body": text, "preview_url": options.link_preview is True},
                    },
                )
            )

        return run

    def edit(
        self, thread: ChatThread, message_id: str, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]:
        return self._unsupported("edit", "edit")

    def delete(self, thread: ChatThread, message_id: str) -> Effect[None, ChatError]:
        return self._unsupported("delete", "delete")

    def fetch_message(self, thread: ChatThread, message_id: str) -> Effect[ChatMessage, ChatError]:
        return self._unsupported("fetchMessage", "fetchMessage")

    def history(
        self,
        thread: ChatThread,
        *,
        direction: Literal["backward", "forward"],
        from_: str | None = None,
    ) -> Stream[ChatMessage, ChatError]:
        return _stream.fail(_errors.chat_error("history", Unsupported(capability="history")))

    def download(
        self, thread: ChatThread, attachment: Attachment, *, max_bytes: int
    ) -> Stream[bytes, ChatError]:
        """The media's URL from Graph, then a GET of it with the access token,
        failing ``TooLarge`` as soon as more than ``max_bytes`` arrive."""
        op = "download"
        too_large = _errors.chat_error(op, TooLarge(subject="files", detail="max_bytes"))

        @fx.gen
        def make() -> Generator[Effect[Any, ChatError, Any], Any, Stream[bytes, ChatError]]:
            yield from self._resolve(op, thread)
            if attachment.size is not None and attachment.size > max_bytes:
                yield from fx.fail(too_large)
            answer: Json = yield from self._graph.call(
                percent_encode(attachment.id), params={"phone_number_id": self._phone_number_id}
            ).map_error(lambda error: _errors.chat_error(op, error.reason))
            info = _json.as_object(answer)
            url = _json.string(info, "url")
            if url is None:
                yield from self._fail(op, _errors.invalid_response(False, "missing_url"))
            size = None if info is None else info.get("file_size")
            if isinstance(size, (int, float)) and not isinstance(size, bool) and size > max_bytes:
                yield from fx.fail(too_large)
            response = yield from self._http.execute(
                http_request.get(str(url)).bearer_token(redacted_value(self._access_token))
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
        return self._unsupported("startThread", "startThread")

    def get_thread(self, thread: ChatThread) -> Effect[ThreadInfo, ChatError]:
        """Built from the address alone, as ``direct``."""
        return self._resolve("getThread", thread).map(
            lambda user: ThreadInfo(
                thread=thread,
                kind="direct",
                raw={"phoneNumberId": self._phone_number_id, "user": user},
            )
        )

    def opener(self, thread: ChatThread) -> Effect[ChatMessage | None, ChatError]:
        """Always ``None``: a WhatsApp address is a direct conversation."""
        return self._resolve("opener", thread).as_(None)

    def get_user(self, id: str, *, in_: ChatThread | None = None) -> Effect[User, ChatError]:
        return self._unsupported("getUser", "getUser")

    def follow_up(
        self, deferred: Defer, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]:
        return self._unsupported("followUp", "commands")

    # --- the WhatsApp side -----------------------------------------------------------

    def send_template(self, thread: ChatThread, template: Template) -> Effect[Posted, ChatError]:
        op = "sendTemplate"
        content: dict[str, object] = {
            "name": template.name,
            "language": {"code": template.language},
        }
        if template.components is not None:
            content["components"] = list(template.components)
        return self._resolve(op, thread).flat_map(
            lambda user: self._send(op, thread, user, {"type": "template", "template": content})
        )

    def mark_read(
        self, thread: ChatThread, message_id: str, *, typing: bool = False
    ) -> Effect[None, ChatError]:
        body: dict[str, object] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        if typing:
            body["typing_indicator"] = {"type": "text"}
        return (
            self._resolve("markRead", thread)
            .flat_map(lambda _: self._graph.call(self._messages_path(), body=body, write=True))
            .map_error(lambda error: _errors.chat_error("markRead", error.reason))
            .as_void()
        )


def percent_encode(text: str) -> str:
    """JavaScript's ``encodeURIComponent``, a lone surrogate as U+FFFD."""
    return quote(to_well_formed(text), safe="-_.!~*'()")
