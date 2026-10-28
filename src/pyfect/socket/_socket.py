"""The socket model (Effect's ``Socket``): a reader and writer acquired in
a scope, and the channels and streams built on them."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Never

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._js import text_decoder, text_encode
from pyfect.cause import Cause
from pyfect.channel import Channel, from_transform
from pyfect.channel import unwrap as unwrap_channel
from pyfect.context import Tag
from pyfect.effect import fail, fail_cause, gen, provide_service, succeed, suspend
from pyfect.exit import Success
from pyfect.pull import filter_no_done
from pyfect.redacted import Redacted
from pyfect.scope import CloseableScope, Scope, fork_in
from pyfect.socket._errors import CloseEvent, SocketError, is_clean_close, upgrade_error
from pyfect.stream import Stream, from_channel

type Chunk = bytes | str
type Write = Callable[[Chunk | CloseEvent], Effect[None, SocketError]]
type WriteAll = Callable[[Sequence[Chunk]], Effect[None, SocketError]]

type PemInput = str | bytes


@dataclass(frozen=True, slots=True, kw_only=True)
class TlsUpgradeOptions:
    """How to upgrade a connection to TLS. ``key`` and ``cert`` (PEM) go
    together; a server needs both. ``servername`` is the client's SNI name
    and the name its certificate check expects."""

    servername: str | None = None
    key: Redacted[PemInput] | Sequence[Redacted[PemInput]] | None = None
    cert: PemInput | Sequence[PemInput] | None = None
    ca: PemInput | Sequence[PemInput] | None = None
    passphrase: Redacted[str] | None = None
    alpn_protocols: Sequence[str] | None = None
    request_cert: bool | None = None
    reject_unauthorized: bool | None = None


type Upgrade = Callable[[TlsUpgradeOptions | None], Effect[None, SocketError]]


def unsupported_upgrade(_options: TlsUpgradeOptions | None = None) -> Effect[None, SocketError]:
    """The upgrade of a socket that cannot do TLS (Effect's
    ``SocketUpgradeError.unsupported``)."""
    return fail(upgrade_error())


class Reader:
    """What a socket's reader gives: ``pull`` waits for the next non-empty
    batch of chunks; ``upgrade`` switches the connection to TLS."""

    __slots__ = ("_upgrade", "pull")

    def __init__(
        self, pull: Effect[tuple[Chunk, ...], SocketError], upgrade: Upgrade = unsupported_upgrade
    ) -> None:
        require_effect(pull, "pull")
        self.pull = pull
        self._upgrade = upgrade

    def upgrade(self, options: TlsUpgradeOptions | None = None) -> Effect[None, SocketError]:
        return self._upgrade(options)


@dataclass(frozen=True, slots=True)
class Writer:
    """What a socket's writer gives: ``write`` sends one chunk (a
    ``CloseEvent`` closes the socket), ``write_all`` a non-empty batch."""

    write: Write
    write_all: WriteAll


@dataclass(frozen=True, slots=True)
class SocketService:
    """A socket: acquiring ``reader`` in a scope opens it (until the scope
    closes); ``writer`` writes to the open connection, waiting for one."""

    reader: Effect[Reader, SocketError, Scope]
    writer: Effect[Writer, Never, Scope]


class Socket(Tag[SocketService], key="effect/socket/Socket"):
    """The socket service."""


def make(
    reader: Effect[Reader, SocketError, Scope], writer: Effect[Writer, Never, Scope]
) -> SocketService:
    require_effect(reader, "reader")
    require_effect(writer, "writer")
    return SocketService(reader, writer)


def encode_chunk(chunk: Chunk) -> bytes:
    """A chunk as bytes: text as ``TextEncoder`` encodes it."""
    return text_encode(chunk) if isinstance(chunk, str) else chunk


def reader_bytes(
    socket: SocketService,
) -> Effect[Effect[tuple[bytes, ...], SocketError], SocketError, Scope]:
    """The reader's pull, with text frames encoded as UTF-8."""
    return socket.reader.map(lambda reader: reader.pull.map(lambda c: tuple(map(encode_chunk, c))))


def reader_string(
    socket: SocketService, encoding: str = "utf-8"
) -> Effect[Effect[tuple[str, ...], SocketError], SocketError, Scope]:
    """The reader's pull, decoding bytes with ``encoding`` across pulls. An
    incomplete character is flushed (as U+FFFD) before a text frame and on a
    normal close."""

    def make_pull(reader: Reader) -> Effect[tuple[str, ...], SocketError]:
        decoder = text_decoder(encoding)
        state = {"needs_flush": False}

        def flush() -> str:
            state["needs_flush"] = False
            text = decoder.decode(b"", final=True)
            decoder.reset()
            return text

        def decode(chunk: tuple[Chunk, ...]) -> tuple[str, ...]:
            out: list[str] = []
            for item in chunk:
                if isinstance(item, str):
                    out.append(flush() + item if state["needs_flush"] else item)
                else:
                    out.append(decoder.decode(item))
                    state["needs_flush"] = True
            return tuple(out)

        def on_error(error: SocketError) -> Effect[tuple[str, ...], SocketError]:
            if state["needs_flush"] and is_clean_close(error):
                last = flush()
                if last:
                    return succeed((last,))
            return fail(error)

        return reader.pull.map(decode).catch_all(on_error)

    return socket.reader.map(make_pull)


def _write_chunk(writer: Writer, chunk: Sequence[Chunk | CloseEvent]) -> Effect[None, SocketError]:
    for index, item in enumerate(chunk):
        if isinstance(item, CloseEvent):
            return _write_each(writer, chunk[: index + 1])
    return writer.write_all(chunk)  # pyright: ignore[reportArgumentType]


def _write_each(writer: Writer, items: Sequence[Chunk | CloseEvent]) -> Effect[None, SocketError]:
    def body():
        for item in items:
            yield from writer.write(item)

    return gen(body)


type SocketChannel[A, IE] = Channel[
    tuple[A, ...], SocketError | IE, None, tuple[Chunk | CloseEvent, ...], IE, object
]


def _to_channel_with_reader[A: Chunk, IE](
    socket: SocketService,
    reader: Effect[Effect[tuple[A, ...], SocketError], SocketError, Scope],
) -> SocketChannel[A, IE]:
    def transform(
        upstream: Effect[tuple[Chunk | CloseEvent, ...], Any], scope: CloseableScope
    ) -> Effect[Effect[tuple[A, ...], Any], Any, Any]:
        def body():
            read_scope = yield from scope.fork()
            pull = yield from reader.pipe(_in_scope(read_scope))
            write_scope = yield from scope.fork()
            writer = yield from socket.writer.pipe(_in_scope(write_scope))
            failure: list[Cause[Any]] = []

            def on_write_failure(_: object, cause: Cause[Any]) -> Effect[None]:
                failure.append(cause)
                # Closing the read scope fails a suspended pull, which is the
                # reader contract, so the read side needs no per-pull race.
                return read_scope.close(Success(None))

            writing = (
                upstream.flat_map(lambda chunk: _write_chunk(writer, chunk))
                .forever()
                .catch_cause_filter(filter_no_done, on_write_failure)
                .ensuring(write_scope.close(Success(None)))
            )
            yield from fork_in(writing, scope)
            return suspend(lambda: fail_cause(failure[0]) if failure else pull).catch_cause(
                lambda cause: fail_cause(failure[0] if failure else cause)
            )

        return gen(body)

    return from_transform(transform)


def _in_scope[A, E](scope: CloseableScope) -> Callable[[Effect[A, E, Scope]], Effect[A, E]]:
    return provide_service(Scope, scope)


def to_channel[IE = Never](socket: SocketService) -> SocketChannel[bytes, IE]:
    """The socket as a channel: its input chunks are written (a
    ``CloseEvent`` closes the socket), its output is what the reader pulls,
    as bytes. A failed write fails the channel."""
    return _to_channel_with_reader(socket, reader_bytes(socket))


def to_channel_string[IE = Never](
    socket: SocketService, encoding: str = "utf-8"
) -> SocketChannel[str, IE]:
    """``to_channel``, with the output decoded as by ``reader_string``."""
    return _to_channel_with_reader(socket, reader_string(socket, encoding))


def to_stream(socket: SocketService) -> Stream[bytes, SocketError]:
    """What the socket's reader pulls, as a stream of bytes."""
    channel: Channel[tuple[bytes, ...], SocketError] = from_transform(
        lambda _upstream, scope: reader_bytes(socket).pipe(_in_scope(scope))
    )
    return from_channel(channel)


def make_channel[IE = Never]() -> Channel[
    tuple[bytes, ...], SocketError | IE, None, tuple[Chunk | CloseEvent, ...], IE, object, Socket
]:
    """``to_channel`` of the ``Socket`` service."""

    def channel(socket: SocketService) -> SocketChannel[bytes, IE]:
        return to_channel(socket)

    return unwrap_channel(Socket().map(channel))
