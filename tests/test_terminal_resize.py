"""The terminal's resize thread lives only while something listens, as Effect's ``size``
stream removes its ``resize`` listener when its scope closes."""

import io

from _threads import live_threads
from _timing import wait_until

import pyfect as fx
from pyfect import terminal, testing


@testing.live
def test_the_resize_thread_ends_when_the_last_size_stream_closes():
    service = terminal.live(input=0, output=io.StringIO())
    yield from fx.scoped(service.size.tap(lambda _: fx.sync(lambda: None)))
    wait_until(lambda: not live_threads("pyfect-terminal-resize"), what="the resize thread to end")


@testing.live
def test_a_new_size_stream_after_that_starts_it_again():
    service = terminal.live(input=0, output=io.StringIO())
    yield from fx.scoped(service.size.tap(lambda _: fx.sync(lambda: None)))
    wait_until(lambda: not live_threads("pyfect-terminal-resize"), what="the resize thread to end")
    running: list[bool] = []

    def listening(_: object) -> fx.Effect[None]:
        return fx.sync(lambda: running.append(bool(live_threads("pyfect-terminal-resize"))))

    yield from fx.scoped(service.size.tap(listening))
    assert running == [True]
