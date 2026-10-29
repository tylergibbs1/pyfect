"""Ports of Effect's ``test/workers/WorkerError.test.ts``. Each test's
docstring is the Effect test title, prefixed by its describe blocks.

``isWorkerError({ _tag: "WorkerError" })`` is a dict with that tag.
"""

from __future__ import annotations

from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import testing
from pyfect._core import Effect
from pyfect.deferred import Deferred
from pyfect.effect import provide_service, succeed, sync
from pyfect.workers import worker as W
from pyfect.workers.worker_error import (
    WORKER_ERROR_REASON,
    WorkerError,
    WorkerReceiveError,
    WorkerSendError,
    WorkerSpawnError,
    WorkerUnknownError,
    is_worker_error,
)


def test_delegates_message_from_reason() -> None:
    """WorkerError / reason handling / delegates message from reason"""
    error = WorkerError(reason=WorkerSendError(message="Failed to send message to worker"))
    assert error.message == "Failed to send message to worker"
    assert isinstance(error.reason, WorkerSendError)


def test_worker_error_delegates_message_and_cause_from_reason() -> None:
    """WorkerError / reason handling / WorkerError delegates message and cause from reason"""
    cause = RuntimeError("boom")
    reason = WorkerSpawnError(message="Failed to spawn worker", cause=cause)
    assert reason.message == "Failed to spawn worker"
    assert reason.cause is cause
    error = WorkerError(reason=reason)
    assert error.cause is cause
    assert error.__cause__ is cause


def test_matches_wrapper_only() -> None:
    """WorkerError / isWorkerError / matches wrapper only"""
    wrapper = WorkerError(reason=WorkerReceiveError(message="Failed to receive message"))
    assert is_worker_error(wrapper)
    assert not is_worker_error(WorkerReceiveError(message="Failed to receive message"))
    assert not is_worker_error(RuntimeError("regular error"))
    assert not is_worker_error({"_tag": "WorkerError"})


@testing.effect
def test_worker_spawn_error_roundtrip():
    """WorkerError / schema roundtrip / WorkerSpawnError roundtrip"""
    reason = WorkerSpawnError(message="Failed to spawn worker")
    encoded = yield from S.encode_effect(WorkerSpawnError)(reason)
    decoded = yield from S.decode_effect(WorkerSpawnError)(encoded)
    assert isinstance(decoded, WorkerSpawnError)
    assert decoded.message == "Failed to spawn worker"


@testing.effect
def test_worker_error_reason_union_roundtrip():
    """WorkerError / schema roundtrip / WorkerErrorReason union roundtrip"""
    reason = WorkerUnknownError(message="Worker crashed unexpectedly")
    encoded = yield from S.encode_effect(WORKER_ERROR_REASON)(reason)
    decoded = yield from S.decode_effect(WORKER_ERROR_REASON)(encoded)
    assert isinstance(decoded, WorkerUnknownError)
    assert decoded.message == "Worker crashed unexpectedly"


@testing.effect
def test_worker_error_roundtrip():
    """WorkerError / schema roundtrip / WorkerError roundtrip"""
    error = WorkerError(reason=WorkerSendError(message="Failed to send message"))
    encoded = yield from S.encode_effect(WorkerError)(error)
    decoded = yield from S.decode_effect(WorkerError)(encoded)
    assert isinstance(decoded, WorkerError)
    assert isinstance(decoded.reason, WorkerSendError)
    assert decoded.message == "Failed to send message"


class _FailingPort:
    def post_message(self, message: object, transfers: W.Transfers) -> None:
        raise RuntimeError("post failed")


@testing.effect
def test_reports_post_message_failures_as_worker_send_error():
    """WorkerError / buffered sends / reports postMessage failures as WorkerSendError"""
    listening = yield from Deferred[None].make()
    emits: list[W.ListenOptions[_FailingPort]] = []

    def setup(_: W.SetupOptions[object]) -> Effect[_FailingPort, WorkerError]:
        return succeed(_FailingPort())

    def listen(options: W.ListenOptions[_FailingPort]) -> Effect[None]:
        return sync(lambda: emits.append(options)).flat_map(
            lambda _: listening.succeed(None).as_void()
        )

    platform = W.make_platform(setup=setup, listen=listen)
    worker = yield from platform.spawn(0).pipe(provide_service(W.Spawner, lambda _: object()))

    yield from worker.send("buffered")
    run = yield from worker.run(lambda _: succeed(None)).fork()
    yield from listening.wait()
    yield from sync(lambda: emits[0].emit((0,)))
    exit = yield from run.await_exit()

    assert isinstance(exit, Exit.Failure)
    assert not exit.cause.has_dies
    error = exit.cause.squash()
    assert is_worker_error(error)
    assert isinstance(error.reason, WorkerSendError)
