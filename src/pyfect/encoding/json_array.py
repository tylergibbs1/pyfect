"""One JSON array as a stream of its elements (Effect's
``encoding/JsonArray``).

Use it when a large response or file is one JSON document, such as
``[...]`` or ``{"items": [...], "total": n}``, and its elements should be
handled without holding the whole document; use ``ndjson`` when the
producer writes one value per line. The decoders write the elements of
one array, the root by default or the one an RFC 6901 JSON Pointer
selects; each element is held only until it is complete. The rest of the
document is checked and dropped. The encoders write a stream of values as
one array::

    users = body.pipe_through_channel(json_array.decode(pointer="/data"))

The schema variants (``decodeSchema``, ``encodeSchema``, ...) come with
``Schema``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

from pyfect._primitives import _FailCause, _Succeed, _Suspend, _Sync
from pyfect.cause import Cause
from pyfect.cause import fail as fail_cause
from pyfect.channel import Channel, decode_text, from_transform
from pyfect.channel._base import AnyPull, end_with
from pyfect.encoding._json import STRINGIFY_ERRORS, Json, stringify
from pyfect.encoding._json_array_scanner import Config, JsonArrayError, Scanner, make_config
from pyfect.pull import match_effect

__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_ELEMENT_SIZE",
    "JsonArrayError",
    "decode",
    "decode_string",
    "encode",
    "encode_string",
]

DEFAULT_MAX_DEPTH = 1000
DEFAULT_MAX_ELEMENT_SIZE = 16 * 1024 * 1024


def _failed(cause: Cause[Any]) -> AnyPull:
    return _FailCause(cause)


def _decode_pull(upstream: AnyPull, config: Config) -> AnyPull:
    scanner = Scanner(config)
    ended: AnyPull | None = None

    def emit(run: Callable[[list[Json]], None]) -> AnyPull:
        out: list[Json] = []
        try:
            run(out)
        except JsonArrayError as error:
            return _FailCause(fail_cause(error))
        return _Succeed(tuple(out)) if out else pull

    def written(texts: tuple[str, ...]) -> AnyPull:
        def run(out: list[Json]) -> None:
            for text in texts:
                scanner.feed(text, out)

        return emit(run)

    def done(leftover: object) -> AnyPull:
        nonlocal ended
        ended = end_with(leftover)
        return emit(lambda _out: scanner.end())

    def next_pull() -> AnyPull:
        if ended is not None:
            return ended
        return match_effect(upstream, on_success=written, on_failure=_failed, on_done=done)

    pull: AnyPull = _Suspend(next_pull)
    return pull


def decode_string[E = Never, D = None](
    *,
    pointer: str = "",
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_element_size: float = DEFAULT_MAX_ELEMENT_SIZE,
) -> Channel[tuple[Json, ...], E | JsonArrayError, D, tuple[str, ...], E, D]:
    """Parse the text of one JSON document and write the elements of the
    array ``pointer`` selects (``""``: the root), one chunk per input chunk
    that completes any. A leading byte-order mark is dropped.

    ``max_depth`` bounds the nesting of one value (an element that is an
    array or object has depth 1); ``max_element_size`` the characters of
    one value (``math.inf``: unbounded). Both apply to the values outside
    the array too. Bad options raise ``ValueError`` here.

    The document is checked as it streams, so elements of earlier chunks
    may be written before a later error fails the channel (the failing
    chunk's are not). The pointer follows the first occurrence of a key,
    where ``json.loads`` keeps the last; a repeated followed key is a
    ``"Pointer"`` error."""
    config = make_config(pointer, max_depth, max_element_size)
    channel: Channel[tuple[Json, ...], E | JsonArrayError, D, tuple[str, ...], E, D] = (
        from_transform(lambda upstream, _scope: _Sync(lambda: _decode_pull(upstream, config)))
    )
    return channel


def decode[E = Never, D = None](
    *,
    pointer: str = "",
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_element_size: float = DEFAULT_MAX_ELEMENT_SIZE,
) -> Channel[tuple[Json, ...], E | JsonArrayError, D, tuple[bytes, ...], E, D]:
    """``decode_string`` of UTF-8 bytes. A character may span chunks;
    invalid UTF-8 becomes U+FFFD."""
    text: Channel[tuple[str, ...], E, D, tuple[bytes, ...], E, D] = decode_text(ignore_bom=True)
    elements: Channel[tuple[Json, ...], E | JsonArrayError, D, tuple[str, ...], E, D] = (
        decode_string(pointer=pointer, max_depth=max_depth, max_element_size=max_element_size)
    )
    return text.pipe_to(elements)


def _stringify(value: object) -> str:
    try:
        return stringify(value)
    except STRINGIFY_ERRORS as cause:
        raise JsonArrayError("Encode", str(cause), cause=cause) from cause


def encode_string[E = Never, D = None]() -> Channel[
    tuple[str, ...], E | JsonArrayError, D, tuple[object, ...], E, D
]:
    """Write a stream of values as the text of one JSON array, one string
    per input chunk; no values give ``"[]"``. A value with no JSON form (a
    set, an object, ``NaN``) fails with an ``"Encode"`` error after the
    text before it is written."""

    def build(upstream: AnyPull) -> AnyPull:
        started = False
        ended: AnyPull | None = None

        def written(values: tuple[object, ...]) -> AnyPull:
            nonlocal started
            try:
                text = ("," if started else "[") + ",".join(map(_stringify, values))
            except JsonArrayError as error:
                return _FailCause(fail_cause(error))
            started = True
            return _Succeed((text,))

        def done(leftover: object) -> AnyPull:
            nonlocal ended
            ended = end_with(leftover)
            return _Succeed(("]" if started else "[]",))

        def next_pull() -> AnyPull:
            if ended is not None:
                return ended
            return match_effect(upstream, on_success=written, on_failure=_failed, on_done=done)

        return _Suspend(next_pull)

    channel: Channel[tuple[str, ...], E | JsonArrayError, D, tuple[object, ...], E, D] = (
        from_transform(lambda upstream, _scope: _Sync(lambda: build(upstream)))
    )
    return channel


def encode[E = Never, D = None]() -> Channel[
    tuple[bytes, ...], E | JsonArrayError, D, tuple[object, ...], E, D
]:
    """``encode_string`` as UTF-8 bytes."""
    strings: Channel[tuple[str, ...], E | JsonArrayError, D, tuple[object, ...], E, D] = (
        encode_string()
    )
    return strings.map(lambda chunk: tuple(text.encode() for text in chunk))
