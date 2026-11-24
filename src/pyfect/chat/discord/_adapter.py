"""The Discord ``ChatAdapter``: posts, edits, files, history, threads, users
and command answers, over ``DiscordRest``, and the interaction entry."""

from __future__ import annotations

import re
from collections.abc import Callable, Generator, Sequence
from typing import Any, Never, cast

import pyfect as fx
from pyfect import clock as _clock
from pyfect import stream as _stream
from pyfect._core import Effect
from pyfect._json_value import JsonValue
from pyfect.cache import Cache
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat_adapter import (
    Descriptor,
    Direction,
    File,
    Limits,
    Posted,
    ThreadInfo,
    User,
    check_message_length,
    retry_safe,
)
from pyfect.chat.chat_error import (
    FILE_REFUSED,
    AnyReason,
    ChatError,
    InvalidRequest,
    NotFound,
    TooLarge,
)
from pyfect.chat.chat_interaction import Defer, Handler
from pyfect.chat.chat_message import Attachment, ChatMessage, ReplyTo
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.chat_ui import Action
from pyfect.chat.discord import _errors, _interactions, _json, _length, _normalize
from pyfect.chat.discord._interactions import AnswerTo, Payload
from pyfect.chat.discord._json import JsonObject
from pyfect.chat.discord._normalize import SNOWFLAKE, UserFields
from pyfect.chat.discord._options import (
    NO_OPTIONS,
    CurrentPostOptions,
    DiscordPostOptions,
    allowed_mentions,
    flags,
)
from pyfect.chat.discord.discord_rest import DiscordRestService, build_request, path, read_answer
from pyfect.duration import Duration, hours, millis, minutes, zero
from pyfect.exit import Exit, is_success
from pyfect.http import request as http_request
from pyfect.http.client import HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.stream import Stream

type Gen[A] = Generator[Effect[Any, ChatError, Any], Any, A]

DESCRIPTOR = Descriptor(
    platform=_normalize.PLATFORM,
    capabilities=frozenset(
        {
            "edit",
            "delete",
            "fetchMessage",
            "history",
            "download",
            "files",
            "replyTo",
            "startThread",
            "getThread",
            "opener",
            "getUser",
            "buttons",
            "selects",
            "modals",
            "commands",
            "ephemeral",
        }
    ),
    # Components sit beside ``content``, so the elements cost nothing here.
    measure=lambda markdown, _actions=(): _length.code_points(markdown),
    limits=Limits(
        message_length=_length.MESSAGE_LENGTH,
        files_per_message=10,
        upload_bytes=10 * 1024 * 1024,
        min_write_interval=millis(1500),
        follow_up_age=minutes(15),
        actions_per_message=_interactions.ACTIONS_PER_MESSAGE,
        action_data_length=_interactions.ACTION_DATA_LENGTH,
        modal_metadata_length=_interactions.MODAL_METADATA_LENGTH,
        modal_fields=_interactions.MODAL_FIELDS,
    ),
)

_PAGE_SIZE = 100

_THREAD_ALREADY_CREATED = 160004
"""Discord's code for "a thread has already been created for this message"."""
_WRONG_CHANNEL_TYPE = 50024
"""Discord's code for "cannot execute action on this channel type"."""
_UNKNOWN_INTERACTION = 10062
"""Discord's code for "unknown interaction": a callback after the 3 seconds."""
_SPENT_TOKEN = (50027, 10015)
"""Discord's codes for an interaction token it no longer takes. After 15
minutes it answered 401 with 50027 "Invalid Webhook Token"; 10015 "Unknown
Webhook" is from the docs' list and was not seen."""

_CHANNEL_TTL = hours(1)
_WHITESPACE = re.compile(r"\s+")

type SendCallback = Callable[[str, AnswerTo, Payload], Effect[None, ChatError]]
"""Sends one interaction callback: through the REST endpoint for the gateway,
or as the answer to Discord's HTTP request."""


class _Channel:
    """What the adapter reads from a channel."""

    __slots__ = ("created", "guild_id", "id", "name", "parent_id", "raw", "topic", "type")

    def __init__(self, obj: JsonObject, raw: object) -> None:
        self.id = _json.req_str(obj, "id")
        self.type = _json.req_number(obj, "type")
        self.guild_id = _json.opt_str(obj, "guild_id")
        self.parent_id = _json.opt_str(obj, "parent_id")
        self.name = _json.opt_str(obj, "name")
        self.topic = _json.opt_str(obj, "topic")
        metadata = _json.opt_obj(obj, "thread_metadata")
        self.created = None if metadata is None else _json.opt_str(metadata, "create_timestamp")
        self.raw = cast("JsonValue", raw)


def _id_of(raw: object) -> str:
    return _json.string_field(raw, "id") or ""


def _user_name(user: UserFields, nick: str | None) -> str:
    return (
        _json.non_empty(nick)
        or _json.non_empty(user.global_name)
        or _json.non_empty(user.username)
        or user.id
    )


class DiscordAdapter:
    """The adapter (``discord_chat.layer`` builds it with ``make``)."""

    def __init__(
        self,
        *,
        rest: DiscordRestService,
        http: HttpClientService[HttpClientError, Never],
        bot_user_id: Effect[str, ChatError],
        channels: Cache[str, _Channel, ChatError],
        max_retry_after: Duration | None = None,
    ) -> None:
        self._rest = rest
        self._http = http
        self._bot_user_id = bot_user_id
        self._channels = channels
        self._max_retry_after = max_retry_after

    @property
    def descriptor(self) -> Descriptor:
        """Discord's capabilities and limits."""
        return DESCRIPTOR

    @property
    def native_stream(self) -> None:
        """Discord has no native streaming: streamed replies post, then edit."""
        return None

    # --- helpers ---------------------------------------------------------------------

    def _fail(self, op: str, reason: AnyReason) -> Effect[Never, ChatError]:
        return fx.fail(_errors.chat_error(op, reason))

    def _call[A](self, op: str, effect: Effect[A, ChatError]) -> Effect[A, ChatError]:
        """One REST call, its failure as an error of ``op``, retried when
        nothing happened."""
        return retry_safe(
            effect.map_error(lambda error: _errors.with_op(op, error)),
            max_retry_after=self._max_retry_after,
        )

    def _resolve(self, op: str, thread: ChatThread) -> Effect[str, ChatError]:
        if _normalize.is_address(thread):
            return fx.succeed(thread.id)
        return self._fail(op, InvalidRequest(detail="invalid_thread"))

    def _check_id(self, op: str, id: str) -> Effect[str, ChatError]:
        """A message id from the caller, refused unless it is a snowflake, so
        it can't reach another route."""
        if SNOWFLAKE.fullmatch(id) is not None:
            return fx.succeed(id)
        return self._fail(op, InvalidRequest(detail="invalid_message_id"))

    def get_channel(self, op: str, id: str) -> Effect[_Channel, ChatError]:
        """One channel, read now."""

        def decode(raw: object) -> Effect[_Channel, ChatError]:
            found = _normalize.decode_option(lambda obj: _Channel(obj, raw), raw)
            if found is None:
                return self._fail(op, _errors.invalid_response(False, "invalid_channel"))
            return fx.succeed(found)

        return self._call(op, self._rest.get_channel(id)).flat_map(decode)

    def channel(self, op: str, id: str) -> Effect[_Channel, ChatError]:
        """One channel, from the cache: its type, parent and guild never change."""
        return self._channels.get(id).map_error(lambda error: _errors.with_op(op, error))

    def _get_message(self, op: str, channel_id: str, message_id: str) -> Effect[object, ChatError]:
        return self._call(op, self._rest.get_message(channel_id, message_id))

    def _or_none[A](self, effect: Effect[A, ChatError]) -> Effect[A | None, ChatError]:
        """An optional read: ``None`` when the message is gone or the bot may not read it."""
        return effect.catch_if(
            lambda error: error.reason._tag in ("NotFound", "Forbidden"),  # pyright: ignore[reportPrivateUsage]
            lambda _: fx.succeed(None),
        )

    def _message_body(
        self, op: str, markdown: str, actions: Sequence[Action], options: DiscordPostOptions
    ) -> Effect[dict[str, object], ChatError]:
        """A write's message, after the checks every write makes before a
        call. ``components`` is absent when there are none."""

        @fx.gen
        def run() -> Gen[dict[str, object]]:
            found = _interactions.rows(actions)
            if not isinstance(found, list):
                return (yield from self._fail(op, found))
            yield from check_message_length(DESCRIPTOR, op, markdown)
            body: dict[str, object] = {
                "content": markdown,
                "allowed_mentions": allowed_mentions(options),
                "flags": flags(options),
            }
            if found:
                body["components"] = found
            return body

        return run

    # --- writes ----------------------------------------------------------------------

    def post(
        self,
        thread: ChatThread,
        *,
        markdown: str,
        reply_to: ReplyTo | None = None,
        files: Sequence[File] = (),
        actions: Sequence[Action] = (),
    ) -> Effect[Posted, ChatError]:
        """``POST /channels/{id}/messages``, with the files in the same request."""
        op = "post"

        @fx.gen
        def run() -> Gen[Posted]:
            channel_id = yield from self._resolve(op, thread)
            options = yield from CurrentPostOptions()
            body = yield from self._message_body(op, markdown, actions, options)
            # The adapter's own count and size check refuses the file the way Discord would.
            limits = DESCRIPTOR.limits
            if (
                len(files) > limits.files_per_message
                or sum(len(file.content) for file in files) > limits.upload_bytes
            ):
                yield from self._fail(op, TooLarge(subject="files", detail=FILE_REFUSED))
            if reply_to is not None:
                reference: dict[str, object] = {"message_id": reply_to.message_id}
                if options.fail_if_not_exists is False:
                    reference["fail_if_not_exists"] = False
                body["message_reference"] = reference
            if files:
                body["attachments"] = [
                    {"id": str(i), "filename": file.name} for i, file in enumerate(files)
                ]
            create = self._call(op, self._rest.create_message(channel_id, body, files))
            # Discord creates the message and its files in one request, so a denied answer
            # left nothing posted.
            answer = yield from (
                create
                if not files
                else create.map_error(
                    lambda error: _errors.chat_error(op, _errors.file_refused(error.reason))
                )
            )
            id = _json.string_field(answer, "id")
            stamp = _json.string_field(answer, "timestamp")
            if id is None or stamp is None:
                yield from self._fail(op, _errors.invalid_response(True, "missing_id"))
            timestamp = _normalize.parse_timestamp(cast("str", stamp))
            if timestamp is None:
                yield from self._fail(op, _errors.invalid_response(True, "invalid_timestamp"))
            return Posted(cast("str", id), thread, cast("Any", timestamp))

        return run

    def edit(
        self, thread: ChatThread, message_id: str, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]:
        """``PATCH`` the message; empty ``components`` clear the elements there were."""
        op = "edit"

        @fx.gen
        def run() -> Gen[None]:
            channel_id = yield from self._resolve(op, thread)
            options = yield from CurrentPostOptions()
            body = yield from self._message_body(op, markdown, actions, options)
            id = yield from self._check_id(op, message_id)
            yield from self._call(
                op,
                self._rest.update_message(
                    channel_id, id, {**body, "components": body.get("components", [])}
                ),
            )

        return run

    def delete(self, thread: ChatThread, message_id: str) -> Effect[None, ChatError]:
        op = "delete"

        @fx.gen
        def run() -> Gen[None]:
            channel_id = yield from self._resolve(op, thread)
            id = yield from self._check_id(op, message_id)
            yield from self._call(op, self._rest.delete_message(channel_id, id))

        return run

    def start_thread(
        self, thread: ChatThread, message_id: str, *, name: str | None = None
    ) -> Effect[ChatThread, ChatError]:
        """The thread under ``message_id``, named ``name`` or after the
        message's text, cut to 100 characters. A thread is its own answer."""
        op = "startThread"

        @fx.gen
        def run() -> Gen[ChatThread]:
            channel_id = yield from self._resolve(op, thread)
            id = yield from self._check_id(op, message_id)
            options = yield from CurrentPostOptions()
            given = (name or "").strip() or None
            if given is None:
                raw = yield from self._get_message(op, channel_id, id)
                content = _json.string_field(raw, "content") or ""
                text = _WHITESPACE.sub(" ", content).strip()
                given = _length.cut(text, 100) if text else "Thread"
            body: dict[str, object] = {"name": _length.cut(given, 100)}
            if options.auto_archive_duration is not None:
                body["auto_archive_duration"] = options.auto_archive_duration

            def wrong_type(error: ChatError) -> Effect[ChatThread, ChatError]:
                return self.channel(op, channel_id).flat_map(
                    lambda found: (
                        fx.succeed(thread)
                        if _normalize.is_thread_type(found.type)
                        else fx.fail(error)
                    )
                )

            return (
                yield from self._call(
                    op, self._rest.create_thread_from_message(channel_id, id, body)
                )
                .map(lambda answer: _normalize.thread(_json.string_field(answer, "id") or id))
                # The thread under a message has the message's id.
                .catch_if(
                    _errors.has_code(_THREAD_ALREADY_CREATED),
                    lambda _: fx.succeed(_normalize.thread(id)),
                )
                # A message in a thread has no thread of its own: the thread is the answer.
                .catch_if(_errors.has_code(_WRONG_CHANNEL_TYPE), wrong_type)
            )

        return run

    # --- reads -----------------------------------------------------------------------

    def fetch_message(self, thread: ChatThread, message_id: str) -> Effect[ChatMessage, ChatError]:
        op = "fetchMessage"

        @fx.gen
        def run() -> Gen[ChatMessage]:
            channel_id = yield from self._resolve(op, thread)
            id = yield from self._check_id(op, message_id)
            bot_user_id = yield from self._bot_user_id
            raw = yield from self._get_message(op, channel_id, id)
            found = _normalize.to_message(raw, bot_user_id=bot_user_id)
            if found is None:
                return (yield from self._fail(op, NotFound(detail="not_a_message")))
            return found

        return run

    def _resolve_starter(
        self, op: str, raw: object, bot_user_id: str
    ) -> Effect[ChatMessage | None, ChatError]:
        """A history item, with the ``THREAD_STARTER_MESSAGE`` placeholder
        replaced by the opener from the parent channel, or dropped when the
        opener is gone."""
        fields = _normalize.decode_message_fields(raw)
        if fields is None:
            return fx.succeed(None)
        if fields.type != _normalize.THREAD_STARTER_MESSAGE:
            return fx.succeed(_normalize.message(raw, fields, bot_user_id=bot_user_id))
        obj = cast("JsonObject", raw)
        if "referenced_message" in obj:
            referenced = obj["referenced_message"]
            if referenced is None:
                return fx.succeed(None)
            return fx.succeed(_normalize.to_message(referenced, bot_user_id=bot_user_id))
        reference = fields.message_reference
        channel_id = None if reference is None else _json.non_empty(reference.channel_id)
        message_id = None if reference is None else _json.non_empty(reference.message_id)
        if (
            channel_id is None
            or message_id is None
            or SNOWFLAKE.fullmatch(channel_id) is None
            or SNOWFLAKE.fullmatch(message_id) is None
        ):
            return fx.succeed(None)
        return self._or_none(self._get_message(op, channel_id, message_id)).map(
            lambda found: (
                None if found is None else _normalize.to_message(found, bot_user_id=bot_user_id)
            )
        )

    def history(
        self, thread: ChatThread, *, direction: Direction, from_: str | None = None
    ) -> Stream[ChatMessage, ChatError]:
        """``GET /channels/{id}/messages``, a hundred to a page, in either
        direction; a thread's starter placeholder becomes its opener."""
        op = "history"

        @fx.gen
        def make() -> Generator[Effect[Any, ChatError, Any], Any, Stream[ChatMessage, ChatError]]:
            channel_id = yield from self._resolve(op, thread)
            bot_user_id = yield from self._bot_user_id
            sign = -1 if direction == "backward" else 1

            def page(
                cursor: str | None,
            ) -> Effect[tuple[list[object], fx.Option[str | None]], ChatError]:
                def read(answer: object) -> tuple[list[object], fx.Option[str | None]]:
                    found = _json.as_list(answer)
                    ordered = sorted(found, key=_SortKey.of)
                    if sign < 0:
                        ordered.reverse()
                    last = ordered[-1] if ordered else None
                    following = (
                        None
                        if len(found) < _PAGE_SIZE or last is None
                        else fx.Some[str | None](_id_of(last))
                    )
                    return ordered, following

                listed = (
                    self._rest.list_messages(channel_id, before=cursor, limit=_PAGE_SIZE)
                    if direction == "backward"
                    else self._rest.list_messages(channel_id, after=cursor or "0", limit=_PAGE_SIZE)
                )
                return self._call(op, listed).map(read)

            def after(message: ChatMessage | None) -> bool:
                if message is None:
                    return False
                if from_ is None:
                    return True
                return _normalize.compare_ids(message.id, from_) == sign

            return (
                _stream.paginate(from_, page)
                .map_effect(lambda raw: self._resolve_starter(op, raw, bot_user_id))
                .filter(after)
                .map(lambda message: cast("ChatMessage", message))
            )

        return _stream.unwrap(make)

    def opener(self, thread: ChatThread) -> Effect[ChatMessage | None, ChatError]:
        """The message whose id is the thread's: in the thread for a forum
        post, otherwise in the parent channel."""
        op = "opener"

        @fx.gen
        def run() -> Gen[ChatMessage | None]:
            channel_id = yield from self._resolve(op, thread)
            found = yield from self.channel(op, channel_id)
            if not _normalize.is_thread_type(found.type):
                return None
            bot_user_id = yield from self._bot_user_id
            raw = yield from self._or_none(self._get_message(op, channel_id, channel_id))
            parent = _json.non_empty(found.parent_id)
            if raw is None and parent is not None and SNOWFLAKE.fullmatch(parent) is not None:
                raw = yield from self._or_none(self._get_message(op, parent, channel_id))
            return None if raw is None else _normalize.to_message(raw, bot_user_id=bot_user_id)

        return run

    def get_thread(self, thread: ChatThread) -> Effect[ThreadInfo, ChatError]:
        op = "getThread"

        @fx.gen
        def run() -> Gen[ThreadInfo]:
            channel_id = yield from self._resolve(op, thread)
            found = yield from self.get_channel(op, channel_id)
            kind = _normalize.kind_of(found.type)
            parent = _json.non_empty(found.parent_id) if kind == "thread" else None
            created = (
                None if not found.created else _normalize.parse_timestamp(found.created)
            ) or _normalize.snowflake_time(found.id)
            return ThreadInfo(
                thread=thread,
                kind=kind,
                name=None if kind == "direct" else _json.non_empty(found.name),
                topic=_json.non_empty(found.topic),
                parent=None if parent is None else _normalize.thread(parent),
                created_at=created,
                raw=found.raw,
            )

        return run

    def get_user(self, id: str, *, in_: ChatThread | None = None) -> Effect[User, ChatError]:
        """The user, with the guild nick and member as ``raw`` when ``in_``
        is a guild channel and they are a member."""
        op = "getUser"

        @fx.gen
        def run() -> Gen[User]:
            user_id = yield from self._check_id(op, id)
            bot_user_id = yield from self._bot_user_id

            def to_user(user: UserFields, nick: str | None, raw: object) -> User:
                return User(
                    id=user.id,
                    name=_user_name(user, nick),
                    is_bot=user.bot is True,
                    is_self=user.id == bot_user_id,
                    raw=cast("JsonValue", raw),
                )

            guild_id: str | None = None
            if in_ is not None:
                channel_id = yield from self._resolve(op, in_)
                found = yield from self.channel(op, channel_id)
                guild_id = _json.non_empty(found.guild_id)
            if guild_id is not None and SNOWFLAKE.fullmatch(guild_id) is not None:
                member = yield from self._or_none(
                    self._call(op, self._rest.get_guild_member(guild_id, user_id))
                )
                decoded = _normalize.decode_option(_decode_member, member)
                if decoded is not None and decoded[1] is not None:
                    return to_user(decoded[1], decoded[0], member)
            raw = yield from self._call(op, self._rest.get_user(user_id))
            user = _normalize.decode_option(_normalize.decode_user, raw)
            if user is None:
                return (yield from self._fail(op, _errors.invalid_response(False, "invalid_user")))
            return to_user(user, None, raw)

        return run

    def download(
        self, thread: ChatThread, attachment: Attachment, *, max_bytes: int
    ) -> Stream[bytes, ChatError]:
        """Reads the message again for the attachment's URL, then GETs it
        from Discord's CDN with no token, failing ``TooLarge`` as soon as
        more than ``max_bytes`` arrive."""
        op = "download"
        too_large = _errors.chat_error(op, TooLarge(subject="files", detail="max_bytes"))

        def transport(error: HttpClientError) -> ChatError:
            return _errors.chat_error(
                op, _errors.transport(False, type(error.reason).__name__, error)
            )

        @fx.gen
        def make() -> Generator[Effect[Any, ChatError, Any], Any, Stream[bytes, ChatError]]:
            channel_id = yield from self._resolve(op, thread)
            if attachment.size is not None and attachment.size > max_bytes:
                yield from fx.fail(too_large)
            ids = _normalize.parse_attachment_id(attachment.id)
            if ids is None or SNOWFLAKE.fullmatch(ids[0]) is None:
                return (yield from self._fail(op, InvalidRequest(detail="invalid_attachment")))
            raw = yield from self._get_message(op, channel_id, ids[0])
            obj = _json.as_object(raw)
            listed = [] if obj is None else _json.as_list(obj.get("attachments"))
            match = next((a for a in listed if _json.string_field(a, "id") == ids[1]), None)
            url = _json.string_field(match, "url")
            if url is None or not url.startswith("https://"):
                return (yield from self._fail(op, NotFound(detail="attachment_not_found")))
            response = yield from self._http.execute(http_request.get(url)).map_error(transport)
            if not 200 <= response.status < 300:
                yield from self._fail(
                    op, _errors.reason_for_response(response.status, None, write=False)
                )
            received = 0

            def counted(chunk: bytes) -> Effect[bytes, ChatError]:
                nonlocal received
                received += len(chunk)
                return fx.fail(too_large) if received > max_bytes else fx.succeed(chunk)

            return response.stream.map_error(transport).map_effect(counted)

        return _stream.unwrap(make)

    # --- commands --------------------------------------------------------------------

    def answer_body(
        self, op: str, markdown: str, actions: Sequence[Action]
    ) -> Effect[dict[str, object], ChatError]:
        """The message a ``post`` of the same content sends with the default
        post options, after the same checks: no mentions and no embeds."""
        return self._message_body(op, markdown, actions, NO_OPTIONS)

    def follow_up(
        self, deferred: Defer, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]:
        """Edits the original response of a deferred command in one HTTP
        request, with no bot token and no retry, which could land past the
        expiry check. Refused before the call past ``follow_up_age``, read
        from the interaction's id. A token Discord no longer takes is
        ``interaction_expired`` too."""
        op = "followUp"

        @fx.gen
        def run() -> Gen[None]:
            to = (
                _interactions.follow_up_to(deferred.command.raw)
                if _normalize.is_address(deferred.command.thread)
                else None
            )
            if to is None:
                return (yield from self._fail(op, InvalidRequest(detail="invalid_interaction")))
            now = yield from _clock.current_time_millis()
            age = cast("Duration", DESCRIPTOR.limits.follow_up_age)
            if now - _normalize.snowflake_millis(to.id) >= age.to_millis():
                return (yield from fx.fail(_errors.expired(op)))
            body = yield from self.answer_body(op, markdown, actions)
            request = build_request(
                self._rest.base_url,
                "PATCH",
                path("webhooks", to.application_id, to.token, "messages", "@original"),
                _interactions.with_visibility(body, deferred.visibility),
            )

            def spent(error: ChatError) -> ChatError:
                if any(_errors.has_code(code)(error) for code in _SPENT_TOKEN):
                    return _errors.expired(op, error.reason)
                return error

            yield from read_answer(op, True, self._http.execute(request)).map_error(spent)

        return run

    def send_callback(self, op: str, to: AnswerTo, payload: Payload) -> Effect[None, ChatError]:
        """One callback through Discord's REST endpoint: its answer to an
        interaction from the gateway."""
        return self._call(
            op, self._rest.create_interaction_response(to.id, to.token, payload)
        ).as_void()

    def interaction(
        self, raw: object, deadline: Duration, send: SendCallback
    ) -> Effect[None, Never, Handler]:
        """Normalises an ``INTERACTION_CREATE`` payload, runs the handler
        inside ``deadline`` and answers with ``send``."""
        event = _interactions.normalize(raw)
        to = _interactions.answer_to(raw)
        if event is None or to is None:
            return fx.void
        found = event

        def logged(effect: Effect[None, ChatError]) -> Effect[None]:
            return effect.catch_all(
                lambda error: fx.log_warning(
                    "@effect/chat-discord: an interaction callback failed", error
                )
            )

        def answer(
            origin: ci.ButtonClicked | ci.SelectChanged | ci.CommandInvoked,
            op: str,
            payload: Effect[Payload, ChatError],
        ) -> Effect[None, Never, Handler]:
            """Sends a reply that must land, or tells ``Handler.refused``: a
            reply that fails its checks sends nothing, and a callback that
            comes back ``Unknown interaction`` was late, which is
            ``interaction_expired``."""

            def refused(error: ChatError) -> Effect[None, Never, Handler]:
                late = _errors.has_code(_UNKNOWN_INTERACTION)(error)
                return Handler().flat_map(
                    lambda handler: handler.refused(
                        origin, _errors.expired(op, error.reason) if late else error
                    )
                )

            return payload.flat_map(lambda built: send(op, to, built)).catch_all(refused)

        @fx.gen
        def run() -> Generator[Effect[Any, Never, Any], Any]:
            reply = yield from ci.handle(found, deadline)
            match reply:
                # Too late to answer: Discord shows its own banner.
                case ci.Late():
                    return
                case ci.Ack() | ci.Close():
                    # Type 6 is no answer to a command, so an unhandled one is left to
                    # whoever owns it.
                    if isinstance(found, ci.CommandInvoked):
                        return
                    yield from logged(send("ack", to, _interactions.ACK_CALLBACK))
                case ci.Errors():
                    yield from logged(
                        send("errors", to, _interactions.errors_callback(reply.errors))
                    )
                case ci.OpenModal():
                    origin = cast("ci.ButtonClicked | ci.SelectChanged | ci.CommandInvoked", found)
                    data = _interactions.modal_data(reply.modal)
                    if not isinstance(data, dict):
                        # A click is still answered, so the person sees no failure for a
                        # modal that could not be built. A command has no silent answer, so
                        # it gets none, and Discord shows its own failure.
                        if not isinstance(origin, ci.CommandInvoked):
                            yield from logged(send("ack", to, _interactions.ACK_CALLBACK))
                        handler = yield from Handler()
                        yield from handler.refused(origin, _errors.chat_error("openModal", data))
                        return
                    yield from answer(
                        origin, "openModal", fx.succeed(_interactions.modal_callback(data))
                    )
                case ci.Respond():
                    command = cast("ci.CommandInvoked", found)
                    visibility = reply.visibility
                    yield from answer(
                        command,
                        "respond",
                        self.answer_body("respond", reply.markdown, reply.actions or ()).map(
                            lambda body: _interactions.respond_callback(body, visibility)
                        ),
                    )
                case ci.Defer():
                    command = cast("ci.CommandInvoked", found)
                    yield from answer(
                        command,
                        "defer",
                        fx.succeed(_interactions.defer_callback(reply.visibility)),
                    )

        return run

    # --- the service's extras ----------------------------------------------------------

    def guild(self, thread: ChatThread) -> Effect[str | None, ChatError]:
        """The guild a channel or thread is in, from the cached channel."""
        return self._resolve("guild", thread).flat_map(
            lambda id: self.channel("guild", id).map(lambda found: _json.non_empty(found.guild_id))
        )

    def channel_type(self, id: str) -> Effect[float, ChatError]:
        """A channel's type, for ``dispatch``."""
        if SNOWFLAKE.fullmatch(id) is None:
            return self._fail("dispatch", InvalidRequest(detail="invalid_thread"))
        return self.channel("dispatch", id).map(lambda found: found.type)


def _decode_member(obj: JsonObject) -> tuple[str | None, UserFields | None]:
    user = _json.opt_obj(obj, "user")
    return _json.opt_str(obj, "nick"), None if user is None else _normalize.decode_user(user)


def _channel_ttl(exit: Exit[Any, Any], _key: str) -> Duration:
    return _CHANNEL_TTL if is_success(exit) else zero


class _SortKey:
    """Orders raw messages by id, as snowflakes."""

    __slots__ = ("id",)

    def __init__(self, id: str) -> None:
        self.id = id

    @classmethod
    def of(cls, raw: object) -> _SortKey:
        return cls(_id_of(raw))

    def __lt__(self, other: _SortKey) -> bool:
        return _normalize.compare_ids(self.id, other.id) < 0


def make(
    *,
    rest: DiscordRestService,
    http: HttpClientService[HttpClientError, Never],
    bot_user_id: Effect[str, ChatError],
    max_retry_after: Duration | None = None,
) -> Effect[DiscordAdapter]:
    """Builds the adapter, with its cache of channels: up to 1,024, each for
    an hour; a failed read is not kept."""
    holder: list[DiscordAdapter] = []

    def lookup(id: str) -> Effect[_Channel, ChatError]:
        return holder[0].get_channel("getChannel", id)

    def build(channels: Cache[str, _Channel, ChatError]) -> DiscordAdapter:
        adapter = DiscordAdapter(
            rest=rest,
            http=http,
            bot_user_id=bot_user_id,
            channels=channels,
            max_retry_after=max_retry_after,
        )
        holder.append(adapter)
        return adapter

    return Cache.make(lookup, capacity=1024, time_to_live=_channel_ttl).map(build)


__all__ = ["DESCRIPTOR", "DiscordAdapter", "SendCallback", "make"]
