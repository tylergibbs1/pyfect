"""The Teams ``ChatAdapter``: thread ops over the Connector, and the answers
to commands through the inbound ``serviceUrl``."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from collections.abc import Set as AbstractSet
from datetime import UTC, datetime, timedelta
from typing import Any, Never

import pyfect as fx
from pyfect import stream as _stream
from pyfect._core import Effect
from pyfect._json_value import JsonValue
from pyfect.chat.chat_adapter import (
    Descriptor,
    Direction,
    File,
    Limits,
    Posted,
    ThreadInfo,
    User,
    check_message_length,
)
from pyfect.chat.chat_error import INTERACTION_EXPIRED, AnyReason, Capability, ChatError
from pyfect.chat.chat_interaction import Defer, Visibility
from pyfect.chat.chat_message import Attachment, ChatMessage, ReplyTo
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.chat_ui import Action, Button, Select
from pyfect.chat.teams import _address, _download, _errors, _json, _length, _render
from pyfect.chat.teams._cloud import Cloud, Unverified
from pyfect.chat.teams._connector import Connector, Http, segment
from pyfect.chat.teams._envelope import Button as ButtonClaims
from pyfect.chat.teams._envelope import Envelope
from pyfect.chat.teams._interactions import MODAL_FIELDS, MODAL_METADATA_LENGTH
from pyfect.chat.teams._normalize import bot_id, timestamp, user_id
from pyfect.clock import current_time_millis
from pyfect.duration import hours, seconds
from pyfect.redacted import Redacted
from pyfect.stream import Stream

ACTIONS_PER_MESSAGE = _render.ACTIONS_PER_ROW
"""The adapter's own cap on elements in one message."""

ACTION_DATA_LENGTH = 1_000
"""The adapter's own cap on an element's id plus value, counted as the
signed token that carries them: 329 units of it are the envelope with a
GUID app and tenant, which leaves about 500 ASCII characters."""

FOLLOW_UP_AGE = hours(24)
"""How long a targeted message can be answered."""

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def capabilities_of(unverified: Unverified, has_keys: bool) -> frozenset[Capability]:
    found: set[Capability] = {"edit", "delete", "getThread", "getUser"}
    if unverified.start_thread:
        found.add("startThread")
    if unverified.download:
        found.add("download")
    if has_keys and unverified.buttons:
        found.add("buttons")
        if unverified.modals:
            found |= {"modals", "modalErrors"}
    if unverified.commands:
        found |= {"commands", "ephemeral"}
    return frozenset(found)


def _no_keys(_button: Button) -> int:
    return 0


def make_descriptor(
    capabilities: frozenset[Capability], token_length: _length.TokenLength = _no_keys
) -> Descriptor:
    buttons = "buttons" in capabilities
    modals = "modals" in capabilities
    return Descriptor(
        platform=_address.PLATFORM,
        capabilities=capabilities,
        measure=_length.make_measure(token_length),
        limits=Limits(
            message_length=_length.MESSAGE_LENGTH,
            files_per_message=0,
            upload_bytes=0,
            min_write_interval=seconds(1),
            actions_per_message=ACTIONS_PER_MESSAGE if buttons else None,
            action_data_length=ACTION_DATA_LENGTH if buttons else None,
            modal_metadata_length=MODAL_METADATA_LENGTH if modals else None,
            modal_fields=MODAL_FIELDS if modals else None,
            follow_up_age=FOLLOW_UP_AGE if "commands" in capabilities else None,
        ),
    )


def _fail(op: str, reason: AnyReason) -> Effect[Never, ChatError]:
    return fx.fail(_errors.chat_error(op, reason))


def _unsupported(op: str, capability: Capability) -> Effect[Never, ChatError]:
    return _fail(op, _errors.unsupported(capability))


def _activities(conversation_id: str) -> str:
    return f"/v3/conversations/{segment(conversation_id)}/activities"


type _Gen[A] = Generator[Effect[Any, ChatError, Any], Any, A]


class TeamsAdapter:
    """The adapter for one bot in one tenant (``teams_chat.layer`` builds it)."""

    def __init__(
        self,
        *,
        connector: Connector,
        http: Http,
        cloud: Cloud,
        app_id: str,
        envelope: Envelope | None,
        unverified: Unverified,
        token: Effect[Redacted[str], ChatError],
        modal_buttons: AbstractSet[str],
    ) -> None:
        self.capabilities = capabilities_of(unverified, envelope is not None)
        self._descriptor = make_descriptor(
            self.capabilities, _no_keys if envelope is None else envelope.token_length_of
        )
        self._connector = connector
        self._http = http
        self._cloud = cloud
        self._self_id = bot_id(app_id)
        self._envelope = envelope
        self._token = token
        self.modal_buttons = frozenset(modal_buttons)

    @property
    def descriptor(self) -> Descriptor:
        return self._descriptor

    @property
    def native_stream(self) -> None:
        """Teams has no native stream here."""
        return None

    # --- helpers ---------------------------------------------------------------------

    def _address(self, op: str, thread: ChatThread) -> Effect[_address.Parts, ChatError]:
        parts = _address.parts(thread)
        if parts is None:
            return _fail(op, _errors.invalid_request("invalid_thread"))
        return fx.succeed(parts)

    def _check_id(self, op: str, id: str) -> Effect[None, ChatError]:
        if not id or len(id) > _address.MAX_ID_LENGTH:
            return _fail(op, _errors.invalid_request("invalid_id"))
        return fx.void

    def _body(
        self, op: str, conversation_id: str, markdown: str, actions: Sequence[Action]
    ) -> Effect[dict[str, object], ChatError]:
        """The activity body for Markdown and elements: the text form without
        elements, one card with them. Checks capabilities and limits first."""
        envelope = self._envelope

        @fx.gen
        def run() -> _Gen[dict[str, object]]:
            if any(isinstance(action, Select) for action in actions):
                return (yield from _unsupported(op, "selects"))
            if actions and ("buttons" not in self.capabilities or envelope is None):
                return (yield from _unsupported(op, "buttons"))
            yield from check_message_length(self._descriptor, op, markdown, actions)
            if not actions or envelope is None:
                return _render.text_activity(markdown)
            if len(actions) > ACTIONS_PER_MESSAGE:
                return (yield from _fail(op, _errors.too_large(None, "too_many_actions")))
            tokens: dict[int, str] = {}
            for action in actions:
                if not isinstance(action, Button):
                    continue
                if envelope.token_length_of(action) > ACTION_DATA_LENGTH:
                    return (yield from _fail(op, _errors.too_large(None, "action_data_too_long")))
                tokens[id(action)] = yield from envelope.sign_button(
                    conversation_id, ButtonClaims(action.id, action.value)
                ).map_error(lambda reason: _errors.chat_error(op, reason))
            return _render.card_activity(
                markdown,
                actions,
                lambda button: tokens[id(button)],
                lambda button: button.id in self.modal_buttons,
            )

        return run

    def _activity_id(self, op: str, answer: JsonValue | None) -> Effect[str, ChatError]:
        found = _json.string(answer, "id")
        if found is None:
            return _fail(op, _errors.invalid_response(True, "missing_id"))
        return fx.succeed(found)

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
        op = "post"

        @fx.gen
        def run() -> _Gen[Posted]:
            parts = yield from self._address(op, thread)
            if files:
                return (yield from _unsupported(op, "files"))
            if reply_to is not None:
                return (yield from _unsupported(op, "replyTo"))
            activity = yield from self._body(op, parts.conversation_id, markdown, actions)
            answer = yield from self._connector.call(
                "POST", _activities(parts.conversation_id), activity, write=True, op=op
            )
            found = yield from self._activity_id(op, answer)
            now = yield from current_time_millis()
            return Posted(found, thread, _EPOCH + timedelta(milliseconds=now))

        return run

    def edit(
        self, thread: ChatThread, message_id: str, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]:
        op = "edit"

        @fx.gen
        def run() -> _Gen[None]:
            parts = yield from self._address(op, thread)
            yield from self._check_id(op, message_id)
            activity = yield from self._body(op, parts.conversation_id, markdown, actions)
            yield from self._connector.call(
                "PUT",
                f"{_activities(parts.conversation_id)}/{segment(message_id)}",
                {**activity, "id": message_id},
                write=True,
                op=op,
            )

        return run

    def delete(self, thread: ChatThread, message_id: str) -> Effect[None, ChatError]:
        op = "delete"

        @fx.gen
        def run() -> _Gen[None]:
            parts = yield from self._address(op, thread)
            yield from self._check_id(op, message_id)
            yield from self._connector.call(
                "DELETE",
                f"{_activities(parts.conversation_id)}/{segment(message_id)}",
                write=True,
                op=op,
            )

        return run

    def fetch_message(self, thread: ChatThread, message_id: str) -> Effect[ChatMessage, ChatError]:
        return _unsupported("fetchMessage", "fetchMessage")

    def history(
        self, thread: ChatThread, *, direction: Direction, from_: str | None = None
    ) -> Stream[ChatMessage, ChatError]:
        return _stream.fail(_errors.chat_error("history", _errors.unsupported("history")))

    def download(
        self, thread: ChatThread, attachment: Attachment, *, max_bytes: int
    ) -> Stream[bytes, ChatError]:
        if "download" not in self.capabilities:
            return _stream.fail(_errors.chat_error("download", _errors.unsupported("download")))
        return _download.download(
            attachment.id,
            _download.DownloadOptions(
                max_bytes=max_bytes,
                token=self._token,
                connector_hosts=frozenset(self._cloud.connector_hosts),
                file_host_suffixes=self._cloud.file_host_suffixes,
                http=self._http,
                redirect_hosts=frozenset(self._cloud.redirect_hosts),
            ),
        )

    def start_thread(
        self, thread: ChatThread, message_id: str, *, name: str | None = None
    ) -> Effect[ChatThread, ChatError]:
        op = "startThread"
        if "startThread" not in self.capabilities:
            return _unsupported(op, "startThread")

        @fx.gen
        def run() -> _Gen[ChatThread]:
            parts = yield from self._address(op, thread)
            yield from self._check_id(op, message_id)
            if parts.root is not None:
                return (
                    thread
                    if parts.root == message_id
                    else _address.thread_of(parts.base, message_id)
                )
            if not _address.is_channel(parts.base):
                return (yield from _fail(op, _errors.invalid_request("not_a_channel")))
            if not _address.is_root(message_id):
                return (yield from _fail(op, _errors.invalid_request("invalid_id")))
            return _address.thread_of(parts.base, message_id)

        return run

    def get_thread(self, thread: ChatThread) -> Effect[ThreadInfo, ChatError]:
        op = "getThread"

        @fx.gen
        def run() -> _Gen[ThreadInfo]:
            parts = yield from self._address(op, thread)
            raw = yield from self._connector.call(
                "GET",
                f"/v3/conversations/{segment(parts.base)}/pagedmembers",
                op=op,
                query={"pageSize": "1"},
            )
            return ThreadInfo(
                thread=thread,
                kind=_address.kind(parts.conversation_id),
                parent=None if parts.root is None else _address.thread(parts.base),
                raw=raw,
            )

        return run

    def opener(self, thread: ChatThread) -> Effect[ChatMessage | None, ChatError]:
        return _unsupported("opener", "opener")

    def get_user(self, id: str, *, in_: ChatThread | None = None) -> Effect[User, ChatError]:
        op = "getUser"
        if in_ is None:
            return _fail(op, _errors.invalid_request("thread_required"))
        within = in_

        @fx.gen
        def run() -> _Gen[User]:
            parts = yield from self._address(op, within)
            yield from self._check_id(op, id)
            raw = yield from self._connector.call(
                "GET", f"/v3/conversations/{segment(parts.base)}/members/{segment(id)}", op=op
            )
            record = _json.as_object(raw)
            connector_id = _json.string(raw, "id")
            canonical = user_id(raw)
            if record is None or connector_id is None or canonical is None:
                return (yield from _fail(op, _errors.invalid_response(False, "invalid_member")))
            return User(
                id=canonical,
                name=_json.string(raw, "name") or _json.string(raw, "givenName") or canonical,
                is_bot=connector_id.startswith("28:"),
                is_self=connector_id == self._self_id,
                raw=raw,
            )

        return run

    def follow_up(
        self, deferred: Defer, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]:
        """The answer a command's ``Defer`` promised, through the command's
        own ``serviceUrl``, within 24 hours of the command."""
        op = "followUp"
        if "commands" not in self.capabilities:
            return _unsupported(op, "commands")
        raw = deferred.command.raw

        @fx.gen
        def run() -> _Gen[None]:
            record = _json.as_object(raw)
            sent = None if record is None else timestamp(record)
            now = yield from current_time_millis()
            age = None if sent is None else now - (sent - _EPOCH) / timedelta(milliseconds=1)
            if age is None or age > FOLLOW_UP_AGE.to_millis():
                return (yield from _fail(op, _errors.not_found(INTERACTION_EXPIRED)))
            yield from self.answer(op, raw, markdown, tuple(actions), deferred.visibility)

        return run

    def answer(
        self,
        op: str,
        raw: JsonValue,
        markdown: str,
        actions: tuple[Action, ...],
        visibility: Visibility,
    ) -> Effect[None, ChatError]:
        """Sends a command's answer through the inbound ``serviceUrl`` in
        ``raw``: private as a targeted message to the command's user, public
        as a new post. A failure is never retried in the other form."""

        @fx.gen
        def run() -> _Gen[None]:
            service_url = _json.string(raw, "serviceUrl")
            conversation_id = _json.string(_json.object_(raw, "conversation"), "id")
            message_id = _json.string(raw, "id")
            recipient_id = _json.string(_json.object_(raw, "from"), "id")
            if (
                service_url is None
                or conversation_id is None
                or message_id is None
                or recipient_id is None
            ):
                return (yield from _fail(op, _errors.invalid_request("invalid_command")))
            for each in (conversation_id, message_id, recipient_id):
                yield from self._check_id(op, each)
            activity = yield from self._body(op, conversation_id, markdown, actions)
            if visibility == "ephemeral":
                yield from self._connector.call(
                    "POST",
                    _activities(conversation_id),
                    {
                        **activity,
                        # Only the id: ``_length.A`` reserves it, and an unbounded
                        # name would break the size bound.
                        "recipient": {"id": recipient_id},
                        "entities": [{"type": "targetedMessageInfo", "messageId": message_id}],
                    },
                    write=True,
                    op=op,
                    service_url=service_url,
                    query={"isTargetedActivity": "true"},
                )
            else:
                yield from self._connector.call(
                    "POST",
                    _activities(conversation_id),
                    activity,
                    write=True,
                    op=op,
                    service_url=service_url,
                )

        return run
