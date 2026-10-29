"""Ports of Effect's ``test/workers/Worker.test.ts``. Each test's docstring
is the Effect test title, prefixed by its describe block.

Effect's ``Deferred.doneUnsafe(deferred, error)`` is
``deferred.unsafe_done(Exit.fail(error))``; ``fiber.pollUnsafe()`` is
``fiber.unsafe_poll()``.
"""

from __future__ import annotations

from collections.abc import Callable

import pyfect as fx
from pyfect import exit as Exit
from pyfect import testing
from pyfect._core import Effect
from pyfect.deferred import Deferred
from pyfect.effect import succeed, sync
from pyfect.workers import worker as W
from pyfect.workers.worker_error import WorkerError, WorkerReceiveError, is_worker_error


class _TestPort:
    def post_message(self, message: object, transfers: W.Transfers) -> None:
        pass


_test_port = _TestPort()

type _OnListen = Callable[[W.ListenOptions[_TestPort]], None]


def _make_platform(on_listen: _OnListen) -> W.WorkerPlatformService:
    def setup(options: W.SetupOptions[_TestPort]) -> Effect[_TestPort, WorkerError]:
        return succeed(options.worker)

    def listen(options: W.ListenOptions[_TestPort]) -> Effect[None]:
        return sync(lambda: on_listen(options))

    return W.make_platform(setup=setup, listen=listen)


_spawner_layer = W.layer_spawner(lambda _: _test_port)

_exit_error = WorkerError(reason=WorkerReceiveError(message="The worker has exited with code: 1"))


def _exit(deferred: Deferred[None, WorkerError]) -> None:
    deferred.unsafe_done(Exit.fail(_exit_error))


def _void(_: object) -> Effect[None]:
    return succeed(None)


@testing.effect
def test_run_fails_when_the_worker_exits_before_the_ready_message():
    """Worker / run fails when the worker exits before the ready message"""

    platform = _make_platform(lambda o: _exit(o.deferred))
    worker = yield from platform.spawn(0).pipe(fx.provide(_spawner_layer))
    error = yield from worker.run(_void).flip()
    assert is_worker_error(error)


@testing.effect
def test_run_fails_when_the_worker_exits_while_waiting_for_ready():
    """Worker / run fails when the worker exits while waiting for ready"""
    found: list[Deferred[None, WorkerError]] = []

    platform = _make_platform(lambda o: found.append(o.deferred))
    worker = yield from platform.spawn(0).pipe(fx.provide(_spawner_layer))
    fiber = yield from worker.run(_void).fork(start_immediately=True)
    assert fiber.unsafe_poll() is None
    found[0].unsafe_done(Exit.fail(_exit_error))
    exit = yield from fiber.await_exit()
    assert Exit.is_failure(exit)


@testing.effect
def test_run_is_interruptible_while_waiting_for_ready():
    """Worker / run is interruptible while waiting for ready"""

    platform = _make_platform(lambda _: None)
    worker = yield from platform.spawn(0).pipe(fx.provide(_spawner_layer))
    fiber = yield from worker.run(_void).fork(start_immediately=True)
    assert fiber.unsafe_poll() is None
    yield from fiber.interrupt()
    exit = yield from fiber.await_exit()
    assert isinstance(exit, Exit.Failure)
    assert exit.cause.has_interrupts


@testing.effect
def test_run_still_fails_on_worker_exit_after_ready():
    """Worker / run still fails on worker exit after ready"""
    found: list[Deferred[None, WorkerError]] = []

    def on_listen(options: W.ListenOptions[_TestPort]) -> None:
        found.append(options.deferred)
        options.emit((0,))

    platform = _make_platform(on_listen)
    worker = yield from platform.spawn(0).pipe(fx.provide(_spawner_layer))
    fiber = yield from worker.run(_void).fork(start_immediately=True)
    assert fiber.unsafe_poll() is None
    found[0].unsafe_done(Exit.fail(_exit_error))
    exit = yield from fiber.await_exit()
    assert Exit.is_failure(exit)
