"""Encoding channels and the datagram reader let go of what they handled once
the run ends, without the cycle collector (see ``tests/test_closure_cycles.py``)."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from typing import Any

from _closure_release import Handled, assert_freed_after_run

import pyfect as fx
from pyfect import stream
from pyfect.encoding import csv, json_array, ndjson, tar, xml
from pyfect.scope import scoped
from pyfect.socket.datagram import (
    BackingAddress,
    BackingEvents,
    BackingSocket,
    make_from_backing_socket,
)


def _decoded(value: Handled, text: str | bytes, decoder: Any) -> fx.Effect[Any, Any, Any]:
    return stream.make(value).map(lambda _: text).pipe_through_channel(decoder).run_drain()


def test_csv_decode_frees_its_input() -> None:
    assert_freed_after_run(lambda v: _decoded(v, "a,b\n", csv.decode_string()))


def test_json_array_decode_frees_its_input() -> None:
    assert_freed_after_run(lambda v: _decoded(v, "[1, 2]", json_array.decode_string()))


def test_ndjson_decode_frees_its_input() -> None:
    assert_freed_after_run(lambda v: _decoded(v, b"1\n2\n", ndjson.decode()))


def test_xml_decode_frees_its_input() -> None:
    assert_freed_after_run(lambda v: _decoded(v, "<a/>", xml.decode_string()))


def test_tar_encode_frees_its_entries() -> None:
    def build(value: Handled) -> fx.Effect[Any, Any, Any]:
        entries = stream.make(value).map(lambda _: tar.file("a", b"body"))
        return entries.pipe_through_channel(tar.encode()).run_drain()

    assert_freed_after_run(build)


class _Backing:
    """A platform socket that keeps its events, as the live adapter does."""

    address = BackingAddress("127.0.0.1", 1)
    scope_ids: Mapping[str, int] = {}
    peer = None
    connected = False

    def __init__(self, events: BackingEvents) -> None:
        self.events = events

    def send(self, payload: bytes, destination: BackingAddress | None, done: Any) -> None:
        done(None)

    def send_many(self, payloads: Any, destinations: Any, done: Any) -> None:
        done(None, None)

    def join_multicast(self, group: Any, interface: Any, source: Any) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        pass


def _open_backing(events: BackingEvents) -> fx.Effect[BackingSocket]:
    def open_() -> BackingSocket:
        events.on_packet(b"packet", "127.0.0.1", 2)
        return _Backing(events)

    return fx.sync(open_)


def _keep(_: object) -> None:
    pass


def test_datagram_reader_pull_frees_its_socket() -> None:
    def build(value: Handled) -> fx.Effect[Any, Any, Any]:
        def body() -> Generator[fx.Effect[Any, Any, Any], Any, object]:
            sock = yield from make_from_backing_socket(
                _open_backing, on_error=lambda _: _keep(value)
            )
            reader = yield from sock.reader
            return (yield from reader.pull)

        return fx.gen(body).pipe(scoped)

    assert_freed_after_run(build)
