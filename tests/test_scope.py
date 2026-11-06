"""acquire_release, scoped, finalizer order."""

from typing import Never

import pyfect as fx
from pyfect.testing import run_test as run


def resource(name: str, log: list[str]) -> fx.Effect[str, Never, fx.Scope]:
    return fx.acquire_release(
        fx.sync(lambda: log.append(f"acquire {name}") or name),
        lambda _, ex: fx.sync(lambda: log.append(f"release {name} ({type(ex).__name__})")),
    )


def test_resources_release_in_reverse_order():
    log: list[str] = []

    @fx.gen
    def program():
        a = yield from resource("a", log)
        b = yield from resource("b", log)
        log.append(f"use {a}{b}")

    fx.run_blocking(fx.scoped(program))
    assert log == ["acquire a", "acquire b", "use ab", "release b (Success)", "release a (Success)"]


def test_release_sees_the_failure():
    log: list[str] = []

    @fx.gen
    def program():
        yield from resource("a", log)
        yield from fx.fail("boom")

    fx.run_blocking_exit(fx.scoped(program))
    assert log == ["acquire a", "release a (Failure)"]


def test_interrupted_scope_releases():
    log: list[str] = []

    @fx.gen
    def program():
        fiber = yield from fx.scoped(resource("a", log).and_then(fx.never)).fork()
        yield from fx.yield_now()
        yield from fiber.interrupt()

    run(program)
    assert log == ["acquire a", "release a (Failure)"]


def test_acquire_use_release():
    log: list[str] = []
    eff = fx.acquire_use_release(
        fx.sync(lambda: log.append("acquire") or 1),
        lambda n: fx.sync(lambda: log.append("use") or n + 1),
        lambda _n, _ex: fx.sync(lambda: log.append("release")),
    )
    assert fx.run_blocking(eff) == 2
    assert log == ["acquire", "use", "release"]


def test_fork_scoped_fibers_end_with_the_scope():
    log: list[str] = []

    @fx.gen
    def program():
        yield from fx.never.on_interrupt(fx.sync(lambda: log.append("bg stopped"))).fork_scoped()
        yield from fx.yield_now()
        log.append("scope body done")

    run(fx.scoped(program))
    assert log == ["scope body done", "bg stopped"]
