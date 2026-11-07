"""The Python worker platforms (``python_worker`` / ``python_worker_runner``):
what Effect's Node platform does on the events Node emits, on threads and
child processes."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect, layer, testing
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.deferred import Deferred
from pyfect.queue import Queue
from pyfect.rpc import RpcGroup
from pyfect.rpc import client as rpc_client
from pyfect.rpc import make as rpc_make
from pyfect.rpc import server as rpc_server
from pyfect.rpc import worker as rpc_worker
from pyfect.scope import scoped
from pyfect.workers import (
    ProcessWorker,
    ThreadWorker,
    WorkerError,
    WorkerHandle,
    WorkerPlatform,
    WorkerReceiveError,
    WorkerSendError,
    WorkerSpawnError,
    python_worker,
    python_worker_runner,
    transferable,
)
from pyfect.workers.worker import Worker
from pyfect.workers.worker_runner import WorkerRunnerPlatform

_ECHO = """
import pyfect as fx
from pyfect import effect
from pyfect.workers import python_worker_runner
from pyfect.workers.worker_runner import WorkerRunnerPlatform

@effect.gen
def main():
    runner = yield from WorkerRunnerPlatform().flat_map(lambda p: p.start())
    yield from runner.run(lambda port, message: runner.send(port, ("echo", message)))

fx.run_blocking(main.pipe(fx.provide(python_worker_runner.layer)).or_die())
"""


@effect.gen
def _echo_main():
    runner = yield from WorkerRunnerPlatform().flat_map(lambda p: p.start())

    def handle(port: int, message: object) -> Effect[None, str] | None:
        if message == "fail":
            return fx.fail("handler failed")
        return runner.send(port, ("echo", message))

    yield from runner.run(handle)


def _run_echo() -> None:
    fx.run_blocking(_echo_main.pipe(fx.provide(python_worker_runner.layer)).or_die())


ECHOES: dict[str, Callable[[], WorkerHandle]] = {
    "thread": lambda: ThreadWorker(_run_echo),
    "process": lambda: ProcessWorker(["-c", _ECHO]),
}


def _spawn(handle: WorkerHandle) -> Effect[Worker[Any, Any], WorkerError]:
    return (
        WorkerPlatform()
        .flat_map(lambda platform: platform.spawn(0))
        .pipe(fx.provide(python_worker.layer(lambda _: handle)))
    )


def _run_error(handle: WorkerHandle) -> Effect[WorkerError]:
    return _spawn(handle).flat_map(lambda w: w.run(lambda _: fx.void)).flip()


@pytest.mark.parametrize("backend", list(ECHOES))
@testing.live(timeout="20 seconds")
def test_messages_sent_before_the_worker_is_ready_are_delivered_in_order(backend: str):
    worker = yield from _spawn(ECHOES[backend]())
    yield from worker.send(1)
    yield from worker.send(2)
    replies = yield from Queue[object].unbounded()
    yield from worker.run(replies.offer).fork_scoped()
    assert (yield from replies.take()) == ("echo", 1)
    assert (yield from replies.take()) == ("echo", 2)


@testing.live(timeout="20 seconds")
def test_a_failing_handler_in_the_worker_is_logged_and_the_worker_keeps_serving():
    worker = yield from _spawn(ECHOES["thread"]())
    replies = yield from Queue[object].unbounded()
    yield from worker.run(replies.offer).fork_scoped()
    yield from worker.send("fail")
    yield from worker.send("after")
    assert (yield from replies.take()) == ("echo", "after")


_RAISING = """
import pyfect as fx
from pyfect import effect
from pyfect.workers import python_worker_runner
from pyfect.workers.worker_runner import WorkerRunnerPlatform

def handle(port, message):
    raise ValueError("handler raised")

@effect.gen
def main():
    runner = yield from WorkerRunnerPlatform().flat_map(lambda p: p.start())
    yield from runner.run(handle)

fx.run_blocking(main.pipe(fx.provide(python_worker_runner.layer)))
"""


def _run_raising() -> None:
    exec(_RAISING, {})


RAISING: dict[str, Callable[[], WorkerHandle]] = {
    "thread": lambda: ThreadWorker(_run_raising),
    "process": lambda: ProcessWorker(["-c", _RAISING]),
}


@pytest.mark.parametrize("backend", list(RAISING))
@testing.live(timeout="20 seconds")
def test_a_handler_that_raises_in_the_worker_ends_the_worker(backend: str):
    """Node's message listener throwing is an uncaught exception: the worker
    ends, so the run fails rather than waiting for replies forever."""
    worker = yield from _spawn(RAISING[backend]())
    yield from worker.send("x")
    error = yield from worker.run(lambda _: fx.void).flip()
    assert isinstance(error.reason, WorkerReceiveError)
    if backend == "thread":
        assert isinstance(error.cause, ValueError)
    else:
        assert error.message == "The worker has exited with code: 1"


@testing.live(timeout="20 seconds")
def test_each_run_asks_the_spawner_for_a_new_worker():
    """Effect calls the spawner when a run starts, so a retried run gets a
    fresh worker."""
    spawned: list[int] = []

    def spawn(worker_id: int) -> WorkerHandle:
        spawned.append(worker_id)
        return ThreadWorker(lambda: None)

    worker = yield from (
        WorkerPlatform()
        .flat_map(lambda platform: platform.spawn(7))
        .pipe(fx.provide(python_worker.layer(spawn)))
    )
    assert spawned == []
    yield from worker.run(lambda _: fx.void).flip()
    yield from worker.run(lambda _: fx.void).flip()
    assert spawned == [7, 7]


def _ready_then_close(handle: WorkerHandle) -> Effect[None, WorkerError]:
    """Run the worker until it is ready, then close the run's scope."""

    @effect.gen
    def body():
        ready = yield from Deferred[None].make()
        worker = yield from _spawn(handle)
        yield from worker.run(
            lambda _: fx.void, on_spawn=ready.succeed(None).as_void()
        ).fork_scoped()
        yield from ready.wait()

    return scoped(body)


@testing.live(timeout="20 seconds")
def test_closing_the_run_ends_a_thread_workers_program():
    ended = threading.Event()

    def target() -> None:
        _run_echo()
        ended.set()

    yield from _ready_then_close(ThreadWorker(target))
    assert ended.wait(5)


@testing.live(timeout="20 seconds")
def test_closing_the_run_ends_a_process_workers_program(tmp_path: Path):
    marker = tmp_path / "ended"
    code = _ECHO + f"open({str(marker)!r}, 'w').close()\n"
    yield from _ready_then_close(ProcessWorker(["-c", code]))
    assert marker.exists()


@testing.live(timeout="20 seconds")
def test_a_process_that_exits_before_it_is_ready_fails_the_run_with_its_code():
    error = yield from _run_error(ProcessWorker(["-c", "raise SystemExit(3)"]))
    assert isinstance(error.reason, WorkerReceiveError)
    assert error.message == "The worker has exited with code: 3"


@testing.live(timeout="20 seconds")
def test_a_thread_worker_that_raises_fails_the_run_with_an_error_event():
    def target() -> None:
        raise ValueError("boom")

    error = yield from _run_error(ThreadWorker(target))
    assert error.message == "An error event was emitted"
    assert isinstance(error.cause, ValueError)


@testing.live(timeout="20 seconds")
def test_a_process_that_cannot_start_fails_the_run_with_a_spawn_error():
    error = yield from _run_error(ProcessWorker([], executable="/nonexistent/python"))
    assert isinstance(error.reason, WorkerSpawnError)
    assert isinstance(error.cause, OSError)


@testing.live(timeout="20 seconds")
def test_a_message_that_cannot_be_pickled_fails_the_send():
    worker = yield from _spawn(ECHOES["process"]())
    replies = yield from Queue[object].unbounded()
    yield from worker.run(replies.offer).fork_scoped()
    yield from worker.send(1)
    yield from replies.take()
    error = yield from worker.send(lambda: None).flip()
    assert isinstance(error.reason, WorkerSendError)


@testing.live(timeout="20 seconds")
def test_a_worker_that_does_not_exit_when_closed_is_killed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(python_worker, "CLOSE_TIMEOUT", 0.2)
    pid_file = tmp_path / "pid"
    code = f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"

    @effect.gen
    def body():
        worker = yield from _spawn(ProcessWorker(["-c", code]))
        yield from worker.run(lambda _: fx.void).fork_scoped()
        while not pid_file.exists() or not pid_file.read_text():
            yield from fx.sleep("50 millis")

    started = time.monotonic()
    yield from scoped(body)
    assert time.monotonic() - started < 5
    pid = int(pid_file.read_text())
    assert _gone(pid)


def _gone(pid: int) -> bool:
    """Whether ``pid`` has exited and been reaped, within a few seconds."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_starting_a_runner_outside_a_worker_fails_with_a_spawn_error() -> None:
    start = WorkerRunnerPlatform().flat_map(lambda p: p.start())
    exit = fx.run_blocking_exit(start.pipe(fx.provide(python_worker_runner.layer)))
    assert isinstance(exit, Exit.Failure)
    error = exit.cause.squash()
    assert isinstance(error, WorkerError)
    assert isinstance(error.reason, WorkerSpawnError)
    assert error.message == "not in a worker"


# --- transferables and the RPC initial message -------------------------------------


@testing.effect
def test_a_transferable_schema_reports_encoded_values_to_the_collector():
    blob = transferable.schema(S.String, lambda value: [f"buffer of {value}"])
    collector = transferable.make_collector_unsafe()
    encoded = yield from S.encode_effect(blob)("x").pipe(
        effect.provide_service(transferable.Collector, collector)
    )
    assert encoded == "x"
    assert collector.clear_unsafe() == ["buffer of x"]
    assert (yield from S.encode_effect(blob)("y")) == "y"


class _InitGroup(RpcGroup):
    get_initial = rpc_make("GetInitial", success=S.String)


def _serve_initial() -> None:
    handlers = _InitGroup.to_layer_effect(
        rpc_worker.initial_message(S.String).map(
            lambda value: _InitGroup.handlers().handle(_InitGroup.get_initial)(
                lambda _: fx.succeed(f"started with {value}")
            )
        )
    )
    main = (
        rpc_server.layer(_InitGroup)
        .pipe(layer.provide(handlers))
        .pipe(layer.provide_merge(rpc_server.layer_protocol_worker_runner))
        .pipe(layer.provide(python_worker_runner.layer))
    )
    fx.run_blocking_exit(main.launch())


@testing.live(timeout="20 seconds")
def test_each_rpc_worker_gets_the_initial_message_before_any_request():
    client_layer = (
        layer.effect(_InitClient, rpc_client.make(_InitGroup))
        .pipe(layer.provide(rpc_client.layer_protocol_worker(size=1)))
        .pipe(layer.provide(rpc_worker.layer_initial_message(S.String, fx.succeed("hello"))))
        .pipe(layer.provide(python_worker.layer(lambda _: ThreadWorker(_serve_initial))))
    )
    reply = yield from (
        _InitClient().flat_map(lambda client: client.get_initial()).pipe(fx.provide(client_layer))
    )
    assert reply == "started with hello"


class _InitClient(Tag[_InitGroup], key="InitClient"):
    pass


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"size": 1, "min_size": 1},
        {"size": 1, "min_size": 1, "max_size": 2, "time_to_live": "1 second"},
        {"min_size": 1, "max_size": 2},
    ],
)
def test_a_worker_pool_takes_either_a_size_or_a_min_and_max_size(options: dict[str, Any]) -> None:
    with pytest.raises(TypeError):
        rpc_client.make_protocol_worker(**options)


def _get_initial_through(protocol: fx.Layer[Any, Any, Any]) -> Effect[str, Any, Any]:
    call = rpc_client.make(_InitGroup).flat_map(lambda client: client.get_initial())
    return fx.scoped(call).pipe(
        fx.provide(
            protocol.pipe(
                layer.provide(rpc_worker.layer_initial_message(S.String, fx.succeed("hi")))
            ).pipe(layer.provide(python_worker.layer(lambda _: ThreadWorker(_serve_initial))))
        )
    )


def test_one_worker_protocol_layer_value_serves_every_run_it_is_provided_to() -> None:
    # A layer is a recipe: each run builds its own pool and protocol
    # (Effect's withRunClient makes its state in Effect.suspend).
    protocol = rpc_client.layer_protocol_worker(size=1)
    exits = [fx.run_blocking_exit(_get_initial_through(protocol)) for _ in range(3)]
    assert exits == [Exit.succeed("started with hi")] * 3


class _SlowGroup(RpcGroup):
    slow = rpc_make("Slow", payload=S.Int, success=S.String)


def _serve_slow(worker_id: int) -> None:
    handlers = _SlowGroup.to_layer(
        _SlowGroup.handlers().handle(_SlowGroup.slow)(
            lambda _request: fx.sleep("200 millis").map(lambda _: str(worker_id))
        )
    )
    main = (
        rpc_server.layer(_SlowGroup)
        .pipe(layer.provide(handlers))
        .pipe(layer.provide(rpc_server.layer_protocol_worker_runner))
        .pipe(layer.provide(python_worker_runner.layer))
    )
    fx.run_blocking_exit(main.launch())


def test_each_worker_thread_serves_over_its_own_runner_protocol() -> None:
    # Two workers at once, both built from the one runner layer value: each
    # needs its own request buffer and semaphore (Effect's withRun makes
    # them in Effect.suspend).
    calls = rpc_client.make(_SlowGroup).flat_map(
        lambda client: fx.all(client.slow(1), client.slow(2), concurrency=2)
    )
    protocol = rpc_client.layer_protocol_worker(size=2).pipe(
        layer.provide(python_worker.layer(lambda id_: ThreadWorker(lambda: _serve_slow(id_))))
    )
    exit_ = fx.run_blocking_exit(fx.scoped(calls).pipe(fx.provide(protocol)).timeout("5 seconds"))
    assert isinstance(exit_, fx.Success)
    first, second = exit_.value
    assert first != second, "both requests were served by one worker's server"
