"""Effect's ``test/utils/forkRegistration.ts``: a fork that starts its work at once and ties
it to a scope keeps that tie when the work interrupts the forker during startup, and closing
the scope waits for the work's cleanup."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Never

import pyfect as fx
from pyfect import scope as Scope
from pyfect._fiber import Fiber
from pyfect.scope import CloseableScope

type Fork = Callable[[fx.Effect[Never], CloseableScope], fx.Effect[Any]]


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


def registers_during_startup(fork: Fork) -> Generator[Any, Any]:
    """``fork`` must start ``work`` immediately and tie it to ``scope``."""
    scope = yield from Scope.make()
    started = fx.Deferred[Fiber[Any, Any]]()
    cleaning = fx.Deferred[None]()
    release = fx.Deferred[None]()

    def forking(parent: Fiber[Any, Any]) -> fx.Effect[Any]:
        def interrupt_parent() -> None:
            parent.interrupt_as_unsafe(None)

        work: fx.Effect[Never] = (
            fx.with_fiber(started.succeed)
            .and_then(fx.sync(interrupt_parent))
            .and_then(fx.never)
            .ensuring(cleaning.succeed(None).and_then(release.wait()))
        )
        return fork(work, scope)

    forker = yield from fx.with_fiber(forking).fork()
    child = yield from started.wait()
    assert _interrupted((yield from forker.await_exit()))
    assert child.poll_unsafe() is None
    closing = yield from scope.close(fx.exit.void).fork()
    yield from cleaning.wait()
    yield from fx.yield_now()
    assert closing.poll_unsafe() is None
    yield from release.succeed(None)
    yield from closing.join()
    assert _interrupted((yield from child.await_exit()))
