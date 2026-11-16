"""System DNS lookups share four threads, as Node's ``dns.lookup`` shares
libuv's pool (Effect's ``NodeDns``). Lookups beyond four queue, and one
abandoned (timed out, interrupted) before a thread took it leaves the queue:
slow lookups of names a service is given cannot start a thread each."""

import socket
import threading
from collections.abc import Callable, Iterator
from ipaddress import IPv4Address
from typing import Any

import pytest

import pyfect as fx
from pyfect.net import dns
from pyfect.net.dns import DnsError

_ADDRESS = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 0))


class _SlowResolver:
    """A ``getaddrinfo`` that holds every call until ``release``, noting
    the hosts it was called for and the threads it ran on."""

    def __init__(self) -> None:
        self.released = threading.Event()
        self._lock = threading.Lock()
        self.hosts: list[str] = []
        self.threads: set[int] = set()

    def __call__(self, host: str, *_args: object, **_kwargs: object) -> list[Any]:
        with self._lock:
            self.hosts.append(host)
            self.threads.add(threading.get_ident())
        self.released.wait(10)
        return [_ADDRESS]


@pytest.fixture
def slow(monkeypatch: pytest.MonkeyPatch) -> Iterator[_SlowResolver]:
    resolver = _SlowResolver()
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    yield resolver
    resolver.released.set()


def _run[A](make: Callable[[dns.DnsService], fx.Effect[A, DnsError]]) -> A:
    return fx.run_blocking(make(dns.make_system()).or_die())


def test_abandoned_lookups_share_four_threads_and_never_start(slow: _SlowResolver) -> None:
    abandoned = _run(
        lambda system: fx.all(
            *[system.lookup(f"slow-{i}.test").timeout_option("50 millis") for i in range(50)],
            concurrency="unbounded",
        )
    )
    assert all(found is None for found in abandoned)
    assert len(slow.hosts) == 4
    slow.released.set()
    # Queued after the abandoned ones: it runs only once they have left the queue.
    assert _run(lambda system: system.lookup("after.test")) == (IPv4Address("192.0.2.1"),)
    assert slow.hosts[4:] == ["after.test"]
    assert len(slow.hosts) == 5
    assert len(slow.threads) <= 4


def test_a_lookup_beyond_four_waits_for_a_thread(slow: _SlowResolver) -> None:
    @fx.fn
    def program(system: dns.DnsService):
        lookups = yield from fx.all(
            *[system.lookup(f"queued-{i}.test") for i in range(6)], concurrency="unbounded"
        ).fork()
        while len(slow.hosts) < 4:
            yield from fx.sleep("1 millis")
        yield from fx.sleep("20 millis")
        running = len(slow.hosts)
        slow.released.set()
        return running, (yield from lookups.join())

    running, found = _run(program)
    assert running == 4
    assert len(found) == 6
    assert len(slow.threads) <= 4
