"""Server-Sent Events: a parser, channels and an encoder (Effect's
``encoding/Sse``).

``decode`` reads chunks of text and writes ``Event`` values; a ``retry:``
directive fails it with ``Retry`` (after the events before it), so the
caller can reconnect after ``Retry.duration``. ``encode`` writes events as
SSE text and ends with a ``retry:`` line when its upstream fails with
``Retry``. ``make_parser`` is the push parser both build on.

``decode_schema`` / ``encode_schema`` decode or encode each event's
``{"event", "data", "id"}`` fields (``EventFields``) with a schema;
``decode_data_schema`` reads each event's ``data`` as JSON decoded with a
schema. ``EventSchema`` is the schema of ``Event`` values and
``EventEncoded`` the schema of their fields.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Never, NotRequired, TypedDict, Unpack, cast

from pyfect import channel_schema
from pyfect import schema as S
from pyfect._digits import parse_digits
from pyfect._primitives import _FailCause, _Succeed, _Suspend, _Sync
from pyfect.cause import fail as fail_cause
from pyfect.channel import Channel, from_transform
from pyfect.channel._base import AnyPull, end_with
from pyfect.duration import Duration, Seconds, to_millis
from pyfect.errors import TaggedError
from pyfect.pull import catch_done
from pyfect.schema import transformation as T

__all__ = [
    "DEFAULT_MAX_EVENT_SIZE",
    "AnyEvent",
    "DataEvent",
    "Event",
    "EventEncoded",
    "EventFields",
    "EventSchema",
    "EventTooLarge",
    "Parser",
    "Retry",
    "SseError",
    "decode",
    "decode_data_schema",
    "decode_schema",
    "encode",
    "encode_schema",
    "make_parser",
    "transform_event",
    "write",
]

DEFAULT_MAX_EVENT_SIZE = 10 * 1024 * 1024
"""The most characters a pending event may hold by default (10 Mi)."""


@dataclass(frozen=True, kw_only=True)
class Event:
    """One event: its ``event`` name, its ``data`` lines joined with
    ``\\n``, and the last event ID seen (``None`` before any)."""

    data: str
    event: str = "message"
    id: str | None = None


@dataclass(eq=False)
class Retry(TaggedError):
    """A ``retry:`` directive: reconnect after ``duration`` (seconds, or a
    ``timedelta``), resuming from ``last_event_id``."""

    duration: Duration
    last_event_id: str | None = None


type AnyEvent = Event | Retry
"""What a parser reports and ``write`` writes."""


@dataclass(eq=False)
class EventTooLarge(TaggedError):
    """A pending event grew past ``max_event_size`` characters."""

    max_event_size: int

    @property
    def message(self) -> str:
        return f"Pending SSE event exceeded the maximum size of {self.max_event_size}"


@dataclass(eq=False)
class SseError(TaggedError):
    """Decoding an SSE stream failed, for ``reason``."""

    reason: EventTooLarge

    @property
    def message(self) -> str:
        return self.reason.message


# --- parsing ----------------------------------------------------------------------

_BOM = "﻿"
_LINE_BREAK = re.compile(r"[\r\n]")


class Parser:
    """A push parser: ``feed`` it chunks of text and it reports each
    ``Event`` and ``Retry`` to its callback. Build one with
    ``make_parser``."""

    __slots__ = (
        "_data",
        "_data_size",
        "_discard_lf",
        "_dispatch_empty_named_events",
        "_event_name",
        "_first_chunk",
        "_generation",
        "_last_event_id",
        "_max_event_size",
        "_on_parse",
        "_pending",
        "_pending_size",
    )

    def __init__(
        self,
        on_parse: Callable[[AnyEvent], object],
        max_event_size: int,
        dispatch_empty_named_events: bool,
    ) -> None:
        self._on_parse = on_parse
        self._max_event_size = max_event_size
        self._dispatch_empty_named_events = dispatch_empty_named_events
        # Bumped by ``reset``, so ``feed`` stops when the callback resets.
        self._generation = 0
        self.reset()

    def reset(self) -> None:
        """Drop the pending line and event and the last event ID; the next
        chunk may start with a byte-order mark again."""
        self._generation += 1
        self._first_chunk = True
        self._pending: list[str] = []  # pieces of the unfinished line
        self._pending_size = 0
        self._discard_lf = False  # the last line ended with ``\r``
        self._last_event_id: str | None = None
        self._event_name: str | None = None
        self._data: list[str] = []
        self._data_size = 0

    def feed(self, chunk: str) -> SseError | None:
        """Parse ``chunk``. Returns an ``SseError`` (and resets) when the
        pending event passes ``max_event_size``. If the callback resets the
        parser, the rest of the chunk is dropped; if it raises, the
        exception propagates and the rest of the chunk is dropped."""
        if self._first_chunk and chunk.startswith(_BOM):
            chunk = chunk[len(_BOM) :]
        self._first_chunk = False
        generation = self._generation
        length = len(chunk)
        position = 0
        while position < length:
            if self._discard_lf:
                self._discard_lf = False
                if chunk[position] == "\n":
                    position += 1
                    continue
            found = _LINE_BREAK.search(chunk, position)
            if found is None:
                self._pending.append(chunk[position:])
                self._pending_size += length - position
                break
            end = found.start()
            self._discard_lf = chunk[end] == "\r"
            line = chunk[position:end]
            if self._pending:
                self._pending.append(line)
                line = "".join(self._pending)
                self._pending = []
                self._pending_size = 0
            self._parse_line(line)
            if self._generation != generation:
                return None
            position = end + 1
        if self._pending_size + self._data_size > self._max_event_size:
            error = SseError(EventTooLarge(self._max_event_size))
            self.reset()
            return error
        return None

    def _parse_line(self, line: str) -> None:
        if not line:
            # The end of an event. Clear it first, so a raising callback
            # cannot leak it into the next event.
            name = self._event_name
            data = "".join(self._data)
            self._event_name = None
            self._data = []
            self._data_size = 0
            if data or (self._dispatch_empty_named_events and name):
                event = Event(event=name or "message", id=self._last_event_id, data=data[:-1])
                self._on_parse(event)
            return
        field, colon, value = line.partition(":")
        if colon and value.startswith(" "):
            value = value[1:]
        if field == "data":
            self._data.append(value + "\n")
            self._data_size += len(value) + 1
        elif field == "event":
            self._event_name = value
        elif field == "id" and "\0" not in value:
            self._last_event_id = value
        elif field == "retry" and (millis := parse_digits(value)) is not None:
            self._on_parse(Retry(Seconds(millis / 1000), self._last_event_id))


def make_parser(
    on_parse: Callable[[AnyEvent], object],
    *,
    max_event_size: int = DEFAULT_MAX_EVENT_SIZE,
    dispatch_empty_named_events: bool = False,
) -> Parser:
    """A parser reporting to ``on_parse``. ``max_event_size`` bounds the
    characters of the pending line and event. With
    ``dispatch_empty_named_events``, an event with an ``event:`` name but no
    ``data:`` line is reported with empty data (WHATWG drops it; some
    protocols, such as graphql-sse's ``complete``, use it)."""
    return Parser(on_parse, max_event_size, dispatch_empty_named_events)


def decode[E = Never, D = None](
    *,
    max_event_size: int = DEFAULT_MAX_EVENT_SIZE,
    dispatch_empty_named_events: bool = False,
) -> Channel[tuple[Event, ...], E | Retry | SseError, D, tuple[str, ...], E, D]:
    """Parse chunks of SSE text into events (see ``make_parser``). A
    ``retry:`` directive fails the channel with ``Retry`` once the events
    before it are written; an oversized event fails it with ``SseError``."""

    def build(upstream: AnyPull) -> AnyPull:
        events: list[Event] = []
        retry: Retry | None = None

        def parsed(event: AnyEvent) -> None:
            nonlocal retry
            if isinstance(event, Retry):
                retry = event
            else:
                events.append(event)

        parser = make_parser(
            parsed,
            max_event_size=max_event_size,
            dispatch_empty_named_events=dispatch_empty_named_events,
        )

        def feed(chunk: tuple[str, ...]) -> AnyPull:
            for text in chunk:
                error = parser.feed(text)
                if error is not None:
                    return _FailCause(fail_cause(error))
            return _Succeed(None)

        pump = upstream.flat_map(feed)

        def loop() -> AnyPull:
            if events:
                out = tuple(events)
                events.clear()
                return _Succeed(out)
            if retry is not None:
                return _FailCause(fail_cause(retry))
            return pump.flat_map(lambda _: loop())

        return _Suspend(loop)

    channel: Channel[tuple[Event, ...], E | Retry | SseError, D, tuple[str, ...], E, D] = (
        from_transform(lambda upstream, _scope: _Sync(lambda: build(upstream)))
    )
    return channel


# --- encoding ---------------------------------------------------------------------

_DATA_BREAK = re.compile(r"\r\n|\r|\n")


def write(event: AnyEvent) -> str:
    """The SSE text of ``event`` (Effect's ``encoder.write``): ``id:``,
    ``event:`` (unless ``"message"``) and one ``data:`` line per line of
    data, then a blank line; a ``Retry`` is a ``retry:`` line in
    milliseconds."""
    if isinstance(event, Retry):
        millis = to_millis(event.duration)
        return f"retry: {int(millis) if millis.is_integer() else millis}\n\n"
    text = "" if event.id is None else f"id: {event.id}\n"
    if event.event != "message":
        text += f"event: {event.event}\n"
    return text + "data: " + _DATA_BREAK.sub("\ndata: ", event.data) + "\n\n"


def _is_retry(error: object) -> bool:
    return isinstance(error, Retry)


def encode[E = Never, D = None]() -> Channel[
    tuple[str, ...], E, None, tuple[Event, ...], E | Retry, D
]:
    """Write events as SSE text. When the upstream fails with ``Retry``,
    write its ``retry:`` line and end. Pipe a stream that cannot fail with
    ``Retry`` through it with ``pipe_through_channel_or_fail``."""

    def build(upstream: AnyPull) -> AnyPull:
        retried = False

        def on_retry(retry: Any) -> AnyPull:
            nonlocal retried
            retried = True
            return _Succeed((write(retry),))

        written = upstream.map(lambda chunk: tuple(map(write, chunk)))
        pull = catch_done(written.catch_if(_is_retry, on_retry), lambda _: end_with(None))
        return _Suspend(lambda: end_with(None) if retried else pull)

    channel: Channel[tuple[str, ...], E, None, tuple[Event, ...], E | Retry, D] = from_transform(
        lambda upstream, _scope: _Sync(lambda: build(upstream))
    )
    return channel


# --- schemas ----------------------------------------------------------------------


class EventFields(TypedDict):
    """An event as a schema reads it: no ``id`` before any was seen."""

    event: str
    data: str
    id: NotRequired[str]


class DataEvent[A](TypedDict):
    """An event whose ``data`` was decoded (``decode_data_schema``)."""

    event: str
    id: str | None
    data: A


class _JsonDataFields(TypedDict):
    event: str
    data: object
    id: NotRequired[str]


EventSchema: S.Bottom[Event] = S.instance_of(Event)
"""``Event`` values, as the decoders write them (Effect's ``Sse.Event``)."""

EventEncoded = S.Struct(EventFields)
"""An event's fields (Effect's ``Sse.EventEncoded``): build a schema for
``decode_schema`` on them, ``S.Struct(EventFields, data=...)`` to decode
``data`` too."""


def _fields(event: Event) -> Mapping[str, object]:
    if event.id is None:
        return {"event": event.event, "data": event.data}
    return {"id": event.id, "event": event.event, "data": event.data}


def _event(fields: Mapping[str, object]) -> Event:
    return Event(
        event=cast("str", fields.get("event", "message")),
        id=cast("str | None", fields.get("id")),
        data=cast("str", fields["data"]),
    )


transform_event: T.Transformation[Mapping[str, object], Event] = T.transform(
    decode=_fields, encode=_event
)
"""``Event`` to its fields and back (Effect's ``Sse.transformEvent``): an
absent ``id`` is left out, an absent ``event`` is ``"message"``."""

type _AnyChannel = Channel[Any, Any, Any, Any, Any, Any, Any]


def decode_schema[A, RD, E = Never, D = None](
    schema: S.Codec[A, Mapping[str, object], RD, object],
    /,
    *,
    max_event_size: int = DEFAULT_MAX_EVENT_SIZE,
    dispatch_empty_named_events: bool = False,
    **options: Unpack[S.ParseOptions],
) -> Channel[tuple[A, ...], E | Retry | SseError | S.SchemaError, D, tuple[str, ...], E, D, RD]:
    """``decode``, each event's fields then decoded with ``schema``. An
    event with no ID has no ``id`` key (declare it ``NotRequired``)."""
    events: _AnyChannel = decode(
        max_event_size=max_event_size, dispatch_empty_named_events=dispatch_empty_named_events
    )
    codec = EventSchema.pipe(S.decode_to(schema, transform_event))
    return events.pipe_to(channel_schema.decode(codec, **options))


def decode_data_schema[A, RD, E = Never, D = None](
    schema: S.Codec[A, object, RD, object],
    /,
    *,
    max_event_size: int = DEFAULT_MAX_EVENT_SIZE,
    dispatch_empty_named_events: bool = False,
) -> Channel[
    tuple[DataEvent[A], ...], E | Retry | SseError | S.SchemaError, D, tuple[str, ...], E, D, RD
]:
    """``decode``, each event's ``data`` then parsed as JSON and decoded
    with ``schema``; ``id`` is ``None`` before any was seen."""
    events: _AnyChannel = decode(
        max_event_size=max_event_size, dispatch_empty_named_events=dispatch_empty_named_events
    )
    fields = S.Struct(_JsonDataFields, data=S.from_json_string(schema))
    codec = EventSchema.pipe(S.decode_to(fields, transform_event))
    decoded: _AnyChannel = channel_schema.decode(codec)
    return events.pipe_to(decoded.map(_with_id))


def _with_id(chunk: tuple[Mapping[str, Any], ...]) -> tuple[DataEvent[Any], ...]:
    return tuple(
        DataEvent(event=fields["event"], id=fields.get("id"), data=fields["data"])
        for fields in chunk
    )


def encode_schema[A, RE, E = Never, D = None](
    schema: S.Codec[A, Mapping[str, object], object, RE], /
) -> Channel[tuple[str, ...], E | S.SchemaError, None, tuple[A, ...], E | Retry, D, RE]:
    """``encode`` of each value encoded with ``schema`` into an event's
    fields first (no ``event`` is ``"message"``)."""
    codec = EventSchema.pipe(S.decode_to(schema, transform_event))
    encoded: _AnyChannel = channel_schema.encode(codec)
    return encoded.pipe_to(encode())
