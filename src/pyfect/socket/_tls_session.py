"""TLS over a plain transport, driven with memory BIOs on the socket loop.

asyncio's own TLS transport cannot half-close: once it sends close_notify
it rejects the peer's remaining data. Node's TLS sockets (whose behavior
the sockets follow) keep reading after ``end()``, and so does this session:
``shutdown`` sends close_notify and the read side stays open until the
peer's close_notify or EOF.

A session sends its records to what it is ``over``: the transport, or the
session beneath it, so TLS can run inside TLS as Node's ``TLSSocket`` over
another ``TLSSocket`` does.

Only the loop thread touches a session.
"""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class Lower(Protocol):
    """What a session sends its records over."""

    def writelines(self, list_of_data: Iterable[bytes], /) -> None: ...

    def is_closing(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class Received:
    """What incoming ciphertext decrypted to: ``data``, then the end of the
    peer's stream (``eof``) or a failure (``error``)."""

    data: tuple[bytes, ...] = ()
    eof: bool = False
    error: ssl.SSLError | None = None


class TlsSession:
    __slots__ = ("_incoming", "_lower", "_object", "_outgoing", "_queued", "handshake")

    def __init__(
        self,
        lower: Lower,
        context: ssl.SSLContext,
        *,
        server_side: bool,
        hostname: str | None,
    ) -> None:
        self._lower = lower
        self._incoming = ssl.MemoryBIO()
        self._outgoing = ssl.MemoryBIO()
        self._object = context.wrap_bio(
            self._incoming, self._outgoing, server_side=server_side, server_hostname=hostname
        )
        self.handshake: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        # Plaintext written during the handshake, sent once it is done.
        self._queued: list[bytes] = []

    def start(self, buffered: Iterable[bytes] = ()) -> Received:
        """Begin the handshake; ``buffered`` is ciphertext that arrived
        before it (a client hello read as plain data)."""
        for data in buffered:
            self._incoming.write(data)
        return self._advance()

    def feed(self, received: Received) -> Received:
        """What ``received`` (from the layer beneath) decrypts to; the end
        or failure beneath ends this session's stream too."""
        for data in received.data:
            self._incoming.write(data)
        mine = self._advance()
        return Received(mine.data, eof=mine.eof or received.eof, error=mine.error or received.error)

    def _advance(self) -> Received:
        try:
            if not self.handshake.done():
                try:
                    self._object.do_handshake()
                except ssl.SSLWantReadError:
                    return Received()
                except ssl.SSLError as error:
                    if not self.handshake.done():
                        self.handshake.set_exception(error)
                    return Received()
                self.handshake.set_result(None)
                queued, self._queued = self._queued, []
                for data in queued:
                    self._object.write(data)
            return self._read()
        finally:
            self._flush()

    def _read(self) -> Received:
        if self.handshake.exception() is not None:
            return Received()
        chunks: list[bytes] = []
        while True:
            try:
                chunk = self._object.read(65536)
            except ssl.SSLWantReadError:
                return Received(tuple(chunks))
            except ssl.SSLZeroReturnError:
                return Received(tuple(chunks), eof=True)
            except ssl.SSLError as error:
                return Received(tuple(chunks), error=error)
            if not chunk:
                return Received(tuple(chunks), eof=True)
            chunks.append(chunk)

    def writelines(self, chunks: Iterable[bytes]) -> None:
        if not self.handshake.done():
            self._queued.extend(chunks)
            return
        for data in chunks:
            self._object.write(data)
        self._flush()

    def shutdown(self) -> None:
        """Send close_notify; reading goes on."""
        # Raises SSLWantReadError while the peer's close_notify is due.
        with contextlib.suppress(ssl.SSLWantReadError):
            self._object.unwrap()
        self._flush()

    def _flush(self) -> None:
        data = self._outgoing.read()
        if data and not self._lower.is_closing():
            self._lower.writelines((data,))

    def is_closing(self) -> bool:
        return self._lower.is_closing()
