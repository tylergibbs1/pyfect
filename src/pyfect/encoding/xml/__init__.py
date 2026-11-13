"""XML 1.0 documents as streams of events (Effect's ``encoding/Xml``).

``decode`` and ``decode_string`` turn UTF-8 bytes or text into events, and
``encode`` and ``encode_string`` write events back as XML. ``elements`` collects
repeated elements, such as the items of a feed, into small trees, so that a large
document is processed one record at a time.

The decoder checks that documents are well-formed. It never reads external
resources and never expands entities declared in a DOCTYPE, so external entity
(XXE) and entity expansion attacks do not apply. It does not validate against a
DTD or schema, and reports names as written, without resolving namespaces.
"""
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Never, TypeIs

from pyfect._js import text_encode
from pyfect._primitives import _FailCause, _Succeed, _Suspend  # pyright: ignore[reportPrivateUsage]
from pyfect._public import publish
from pyfect.channel import Channel, from_transform
from pyfect.channel._base import AnyPull, end_with
from pyfect.encoding.xml._chars import is_name, quoted
from pyfect.encoding.xml._collector import Collector
from pyfect.encoding.xml._inputs import Machine, TextInput, Utf8Input
from pyfect.encoding.xml._model import (
    Comment,
    Declaration,
    Doctype,
    Element,
    EndElement,
    Event,
    ProcessingInstruction,
    StartElement,
    Text,
    XmlError,
    XmlErrorKind,
)
from pyfect.encoding.xml._parser import Parser
from pyfect.encoding.xml._writer import Writer
from pyfect.exit import Success
from pyfect.exit import fail as fail_exit
from pyfect.pull import match_effect
from pyfect.scope import CloseableScope

__all__ = [
    "Comment",
    "Declaration",
    "Doctype",
    "Element",
    "EndElement",
    "Event",
    "ProcessingInstruction",
    "StartElement",
    "Text",
    "XmlError",
    "XmlErrorKind",
    "decode",
    "decode_string",
    "elements",
    "encode",
    "encode_string",
    "is_xml_error",
]

_DEFAULT_MAX_TOKEN_SIZE = 10 * 1024 * 1024
_DEFAULT_MAX_DEPTH = 1024
_DEFAULT_MAX_ELEMENT_SIZE = 16 * 1024 * 1024


def is_xml_error(value: object) -> TypeIs[XmlError]:
    return isinstance(value, XmlError)


def _check_limit(name: str, value: float | None, default: int) -> float:
    limit = default if value is None else value
    if not limit > 0:
        raise ValueError(f"Xml: {name} must be positive, got {limit}")
    return limit


def _make_channel(make: Callable[[], Machine[Any, Any]]) -> Any:
    def transform(upstream: AnyPull, _: CloseableScope) -> AnyPull:
        return _Succeed(_Suspend(_DecodePull(upstream, make()).next))

    return from_transform(transform)


class _DecodePull:
    """The decoders' pull: a state object rather than closures over the pull
    itself, so a finished run does not keep its input alive."""

    __slots__ = ("done", "failure", "machine", "upstream")

    def __init__(self, upstream: AnyPull, machine: Machine[Any, Any]) -> None:
        self.upstream = upstream
        self.machine = machine
        self.done: AnyPull | None = None
        self.failure: XmlError | None = None

    def next(self) -> Any:
        if self.failure is not None:
            return fail_exit(self.failure)
        if self.done is not None:
            return self.done
        return match_effect(
            self.upstream, on_success=self.emit, on_failure=_FailCause, on_done=self.ended
        )

    # Output completed before an error is emitted before the failure
    def emit(self, inputs: tuple[Any, ...] | None) -> Any:
        machine = self.machine
        try:
            if inputs is None:
                machine.end()
            else:
                for value in inputs:
                    machine.push(value)
        except XmlError as error:
            self.failure = error
        out = machine.out
        if out:
            machine.out = []
            return Success(tuple(out))
        return _Suspend(self.next)

    def ended(self, leftover: object) -> Any:
        self.done = end_with(leftover)
        return self.emit(None)


def _make_parser(
    max_token_size: float | None, max_depth: float | None, is_bytes: bool
) -> Callable[[], Parser]:
    token = _check_limit("maxTokenSize", max_token_size, _DEFAULT_MAX_TOKEN_SIZE)
    depth = _check_limit("maxDepth", max_depth, _DEFAULT_MAX_DEPTH)
    return lambda: Parser(token, depth, is_bytes)


def decode_string[IE = Never, D = None](
    *, max_token_size: float | None = None, max_depth: float | None = None
) -> Channel[tuple[Event, ...], XmlError | IE, D, tuple[str, ...], IE, D]:
    """A channel decoding XML text chunks into events.

    Tokens can be split anywhere between chunks, and each output chunk holds the
    events one input chunk completed. The document must have one root element;
    whitespace outside it is not reported. A leading byte order mark is skipped,
    the encoding the declaration names is ignored, and events completed before an
    error are written before the channel fails.

    ``max_token_size`` is the most UTF-16 code units one token may take as written
    (10 MiB by default), and ``max_depth`` the most nested elements (1024);
    ``math.inf`` disables either, and a limit that is not positive raises
    ``ValueError``.

    A DOCTYPE is reported, its internal subset skipped and never applied. An
    entity other than the five predefined ones fails with ``"Unsupported"`` when
    the document has a DOCTYPE and ``"Syntax"`` otherwise."""
    parser = _make_parser(max_token_size, max_depth, False)
    return _make_channel(lambda: TextInput(parser()))


def decode[IE = Never, D = None](
    *, max_token_size: float | None = None, max_depth: float | None = None
) -> Channel[tuple[Event, ...], XmlError | IE, D, tuple[bytes, ...], IE, D]:
    """``decode_string`` for UTF-8 bytes. Multi-byte characters can be split
    between chunks. Invalid or truncated UTF-8 fails with ``"Syntax"``; a UTF-16
    byte order mark, or a declaration naming an encoding other than UTF-8 or
    US-ASCII, with ``"Unsupported"`` (decode such bytes yourself and use
    ``decode_string``)."""
    parser = _make_parser(max_token_size, max_depth, True)
    return _make_channel(lambda: Utf8Input(parser()))


def elements[IE = Never, D = None](
    path: Sequence[str], *, max_element_size: float | None = None
) -> Channel[tuple[Element, ...], XmlError | IE, D, tuple[Event, ...], IE, D]:
    """A channel collecting the elements at ``path`` into trees, to process a large
    document one record at a time.

    ``path`` lists element names from the root, and ``"*"`` matches any name. Each
    match is written once its end tag arrives, with all its descendants; everything
    else is skipped. Whitespace between children is kept as strings.

    A collected element over ``max_element_size`` (UTF-16 code units of its names,
    attributes and text; 16 MiB by default, ``math.inf`` disables it) fails with
    ``"Limit"``. The size counts characters, not memory, so use a lower limit for
    untrusted input. An empty path or an invalid name raises ``ValueError``, and a
    ``str`` for ``path``, which would read as one name per letter, ``TypeError``."""
    if isinstance(path, str):
        raise TypeError(f"Xml: elements path must be a sequence of names, got {quoted(path)}")
    if not path:
        raise ValueError("Xml: elements path must not be empty")
    for name in path:
        if name != "*" and not is_name(name):
            raise ValueError(f"Xml: invalid element name in path: {quoted(name)}")
    limit = _check_limit("maxElementSize", max_element_size, _DEFAULT_MAX_ELEMENT_SIZE)
    segments = tuple(path)
    return _make_channel(lambda: Collector(segments, limit))


def encode_string[IE = Never, D = None]() -> Channel[
    tuple[str, ...], XmlError | IE, D, tuple[Event, ...], IE, D
]:
    """A channel writing events as XML text, one string per input chunk.

    Text escapes ``&``, ``<`` and ``>``; attribute values are double-quoted and
    escape ``&``, ``<``, ``"``, tabs and line breaks. Empty elements use explicit
    closing tags (``<br></br>``), and nothing is added between events.

    Events that do not form one well-formed document fail with ``"InvalidEvent"``,
    and the stream must end with the root element closed."""
    return _make_channel(lambda: Writer(False))


def encode[IE = Never, D = None]() -> Channel[
    tuple[bytes, ...], XmlError | IE, D, tuple[Event, ...], IE, D
]:
    """``encode_string`` as UTF-8 bytes. A ``Declaration`` naming another encoding
    fails with ``"InvalidEvent"``."""
    channel: Any = _make_channel(lambda: Writer(True))

    def to_bytes(chunk: tuple[str, ...]) -> tuple[bytes, ...]:
        return tuple(text_encode(text) for text in chunk)

    return channel.map(to_bytes)


publish(globals())
