"""``pyfect.workers.shared_memory``: ports of Effect's ``test/workers/SharedMemory.test.ts``
and of the "shared memory over worker RPC" block of platform-node's
``test/RpcServer.test.ts``. A ported test's docstring is the Effect title, after its
describe blocks.

Then what Python adds: each segment is freed when its scope closes, however it closes,
and a process that dies holding one leaves none behind. On Linux a segment is a file in
``/dev/shm``; elsewhere a freed segment can no longer be opened by name.
"""

from __future__ import annotations

import array
import gc
import os
import pickle
import signal
import sys
import weakref
from collections.abc import Callable
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from typing import Any, cast

import pytest
from _shared_memory_rpc import Compute, FillRange, serve
from _timing import wait_until

import pyfect as fx
from pyfect import exit as Exit
from pyfect import layer
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.result import Ok
from pyfect.rpc import client as rpc_client
from pyfect.workers import ProcessWorker, ThreadWorker, WorkerHandle, WorkerPlatform, python_worker
from pyfect.workers import shared_memory as sm
from pyfect.workers.worker import Worker

TESTS = Path(__file__).parent


def _segment_exists(name: str) -> bool:
    if sys.platform == "linux":
        return Path("/dev/shm", name).exists()
    try:
        SharedMemory(name, track=False).close()
    except FileNotFoundError:
        return False
    return True


def _run[A](program: Effect[A, Any, Any]) -> A:
    exit_ = fx.run_blocking_exit(fx.scoped(program).timeout("20 seconds"))
    assert isinstance(exit_, fx.Success), exit_
    return exit_.value


# --- SharedMemory.test.ts -------------------------------------------------------------


def test_reports_unavailable_memory_when_shared_memory_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SharedMemory / reports unavailable memory when SharedArrayBuffer is undefined: here,
    when multiprocessing.shared_memory is missing"""
    monkeypatch.setitem(sys.modules, "multiprocessing.shared_memory", None)
    assert not sm.is_available()
    exit_ = fx.run_blocking_exit(fx.scoped(sm.make(sm.int32, 1)))
    assert isinstance(exit_, fx.Failure)
    match exit_.cause.find_error():
        case Ok(sm.SharedMemoryError() as error):
            assert "multiprocessing.shared_memory is unavailable" in error.message
        case other:
            pytest.fail(f"expected a SharedMemoryError, got {other}")


def test_accepts_shared_arrays_of_the_requested_kind() -> None:
    """SharedMemory / schema / accepts shared arrays of the requested kind"""
    ints = sm.schema(sm.int32)

    @fx.fn
    def program():
        data = yield from sm.make(sm.int32, 2)
        assert S.decode_unknown_sync(ints)(data) is data

    _run(program())


def test_rejects_unshared_wrong_kind_and_serialized_arrays() -> None:
    """SharedMemory / schema / rejects unshared, wrong-kind and serialized arrays"""
    ints = sm.schema(sm.int32)

    @fx.fn
    def program():
        wrong_kind = yield from sm.make(sm.uint32, 2)
        for data in [array.array("i", [0, 0]), wrong_kind, {0: 0, 1: 0}, [0, 0]]:
            with pytest.raises(S.SchemaError, match="int32 array in shared memory"):
                S.decode_unknown_sync(ints)(data)
        with pytest.raises(S.SchemaError):
            S.encode_unknown_sync(ints)(array.array("i", [0]))

    _run(program())


def test_passes_values_through_the_json_codec_untouched() -> None:
    """SharedMemory / schema / passes values through the JSON codec untouched"""
    codec = S.to_codec_json(S.Struct(FillRange, data=sm.schema(sm.int32)))

    @fx.fn
    def program():
        data = yield from sm.make(sm.int32, 2)
        encoded = S.encode_sync(codec)({"data": data, "start": 0, "stop": 2})
        assert isinstance(encoded, dict)
        assert cast("dict[str, object]", encoded)["data"] is data
        assert S.decode_unknown_sync(codec)(encoded)["data"] is data

    _run(program())


# --- RpcServer.test.ts: shared memory over worker RPC ---------------------------------


def _fill_on_workers(spawn: Callable[[int], WorkerHandle], size: int) -> list[int]:
    @fx.fn
    def program():
        data = yield from sm.make(sm.int32, 4)
        client = yield from rpc_client.make(Compute)
        ranges = [(0, 2), (2, 4)]
        yield from fx.for_each(
            ranges,
            lambda r: client.fill({"data": data, "start": r[0], "stop": r[1]}),
            concurrency="unbounded",
        )
        return data.tolist()

    workers = rpc_client.layer_protocol_worker(size=size).pipe(
        layer.provide(python_worker.layer(spawn))
    )
    return _run(program().pipe(fx.provide(workers)))


def test_worker_threads_write_into_the_callers_shared_array() -> None:
    """shared memory over worker RPC / worker threads write into the caller's shared array"""
    assert _fill_on_workers(lambda _: ThreadWorker(serve), size=2) == [0, 2, 4, 6]


def _process(_: int) -> WorkerHandle:
    return ProcessWorker(["-m", "_shared_memory_rpc"], cwd=TESTS)


def test_worker_processes_write_into_the_callers_shared_array() -> None:
    """Where Effect's child process rejects a shared array, pyfect's shares it (an omission in
    ``_effect_title_omissions.py``): a process worker's message carries the segment's name, so
    the child maps the parent's memory and its writes land there."""
    assert _fill_on_workers(_process, size=2) == [0, 2, 4, 6]


def test_a_worker_process_exiting_leaves_the_parents_segment_in_place() -> None:
    @fx.fn
    def program():
        data = yield from sm.make(sm.int32, 4)
        workers = rpc_client.layer_protocol_worker(size=1).pipe(
            layer.provide(python_worker.layer(_process))
        )
        fill = rpc_client.make(Compute).flat_map(
            lambda client: client.fill({"data": data, "start": 0, "stop": 4})
        )
        # The pool's scope closes here, which ends the worker that mapped the segment.
        yield from fx.scoped(fill).pipe(fx.provide(workers))
        assert _segment_exists(data.name)
        return data.tolist()

    assert _run(program()) == [0, 2, 4, 6]


# --- every segment is freed --------------------------------------------------------------


def _held_by(
    body: Callable[[sm.SharedArray[int]], Effect[object, object]],
) -> tuple[Exit.Exit[object, object], str]:
    names: list[str] = []

    @fx.fn
    def program():
        data = yield from sm.make(sm.int32, 1)
        names.append(data.name)
        assert _segment_exists(data.name)
        return (yield from body(data))

    exit_: Exit.Exit[object, object] = fx.run_blocking_exit(fx.scoped(program()))
    return exit_, names[0]


def _died(exit_: Exit.Exit[object, object]) -> bool:
    return isinstance(exit_, fx.Failure) and isinstance(exit_.cause.find_defect(), Ok)


def _failed_with_boom(exit_: Exit.Exit[object, object]) -> bool:
    return isinstance(exit_, fx.Failure) and exit_.cause.find_error() == Ok("boom")


def _interrupted(exit_: Exit.Exit[object, object]) -> bool:
    return isinstance(exit_, fx.Failure) and exit_.cause.has_interrupts_only


ENDINGS: dict[
    str,
    tuple[
        Callable[[sm.SharedArray[int]], Effect[object, object]],
        Callable[[Exit.Exit[object, object]], bool],
    ],
] = {
    "success": (lambda data: fx.succeed(data[0]), lambda exit_: exit_ == Exit.succeed(0)),
    "failure": (lambda _: fx.fail("boom"), _failed_with_boom),
    "defect": (lambda _: fx.die(RuntimeError("boom")), _died),
    "interrupt": (lambda _: fx.interrupt(), _interrupted),
}


@pytest.mark.parametrize("ending", list(ENDINGS))
def test_a_segment_is_freed_when_its_scope_closes(ending: str) -> None:
    body, ended_so = ENDINGS[ending]
    exit_, name = _held_by(body)
    assert ended_so(exit_), exit_
    assert not _segment_exists(name)


def test_a_segment_is_freed_when_its_fiber_is_interrupted_from_outside() -> None:
    names: list[str] = []

    @fx.fn
    def program():
        latch = yield from fx.Deferred[None].make()

        @fx.fn
        def holder():
            data = yield from sm.make(sm.float64, 8)
            names.append(data.name)
            yield from latch.succeed(None)
            yield from fx.never

        fiber = yield from fx.scoped(holder()).fork()
        yield from latch.wait()
        yield from fiber.interrupt()
        yield from fiber.await_exit()

    _run(program())
    assert not _segment_exists(names[0])


def test_a_process_killed_while_holding_a_segment_leaves_none_behind() -> None:
    names: list[str] = []
    child = """
import os
import pyfect as fx
from pyfect import effect
from pyfect.workers import python_worker_runner
from pyfect.workers import shared_memory as sm
from pyfect.workers.worker_runner import WorkerRunnerPlatform

@effect.gen
def main():
    runner = yield from WorkerRunnerPlatform().flat_map(lambda p: p.start())

    def hold(port, _message):
        held = sm.make(sm.int32, 4).flat_map(lambda d: runner.send(port, (d.name, os.getpid())))
        return fx.scoped(held.and_then(fx.never))

    yield from runner.run(hold)

fx.run_blocking(main.pipe(fx.provide(python_worker_runner.layer)).or_die())
"""

    @fx.fn
    def program():
        worker: Worker[Any, Any] = yield from (
            WorkerPlatform()
            .flat_map(lambda platform: platform.spawn(0))
            .pipe(fx.provide(python_worker.layer(lambda _: ProcessWorker(["-c", child]))))
        )
        replies = yield from fx.Queue[Any].unbounded()
        yield from worker.run(replies.offer).fork_scoped()
        yield from worker.send("hold")
        name, pid = yield from replies.take()
        names.append(name)
        assert _segment_exists(name)
        os.kill(pid, signal.SIGKILL)

    _run(program())
    # The child's resource tracker frees what the child held once the child is gone.
    wait_until(lambda: not _segment_exists(names[0]), what="the killed child's segment to go")


# --- the array --------------------------------------------------------------------------


def test_a_shared_array_reads_and_writes_like_a_list_and_is_zero_filled() -> None:
    @fx.fn
    def program():
        data = yield from sm.make(sm.float64, 4)
        assert data.tolist() == [0.0] * 4
        data[0] = 1.5
        data[2:4] = [2.5, 3.5]
        assert list(data) == [1.5, 0.0, 2.5, 3.5]
        assert data[1:3] == [0.0, 2.5]
        with pytest.raises(ValueError, match="3 values for a slice of 2"):
            data[0:2] = [1.0, 2.0, 3.0]
        empty = yield from sm.make(sm.uint8, 0)
        assert len(empty) == 0
        return data

    data = _run(program())
    with pytest.raises(ValueError, match="released"):
        data[0]
    with pytest.raises(ValueError, match="freed"):
        pickle.dumps(data)


def test_a_pickled_shared_array_maps_the_same_memory() -> None:
    @fx.fn
    def program():
        data = yield from sm.make(sm.int64, 2)
        copy = pickle.loads(pickle.dumps(data))
        copy[1] = 2**40
        assert sm.is_shared(copy)
        assert data[1] == 2**40

    _run(program())


def test_a_dropped_mapped_copy_is_freed() -> None:
    @fx.fn
    def program():
        data = yield from sm.make(sm.int32, 1)
        copy = pickle.loads(pickle.dumps(data))
        mapped = weakref.ref(copy)
        del copy
        gc.collect()
        assert mapped() is None
        data[0] = 1
        return data[0]

    assert _run(program()) == 1


def test_a_negative_length_is_refused_when_make_is_called() -> None:
    with pytest.raises(ValueError, match="negative"):
        sm.make(sm.int32, -1)


def test_a_segment_the_system_refuses_is_a_shared_memory_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = OSError(28, "No space left on device")

    def refuse(*_args: object, **_kwargs: object) -> SharedMemory:
        raise refused

    monkeypatch.setattr("multiprocessing.shared_memory.SharedMemory", refuse)
    exit_ = fx.run_blocking_exit(fx.scoped(sm.make(sm.int32, 1)))
    assert isinstance(exit_, fx.Failure)
    match exit_.cause.find_error():
        case Ok(sm.SharedMemoryError() as error):
            assert error.cause is refused
        case other:
            pytest.fail(f"expected a SharedMemoryError, got {other}")
