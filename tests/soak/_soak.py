"""Runs every workload against one HTTPS server, one HTTP client and one SQLite
database until the duration is up (or SIGTERM / SIGINT), sampling health all along,
then stops everything and records how the shutdown went."""

from __future__ import annotations

import faulthandler
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

import pyfect as fx
from pyfect import Context, layer
from pyfect.http import httpx_client
from pyfect.http.client import HttpClient
from pyfect.http.server import HttpServer
from pyfect.metric import FiberRuntimeMetrics
from pyfect.net.net_address import InetAddressV4
from pyfect.scope import scoped
from pyfect.sql import SqlClient, sqlite

from . import _data, _http, _runtime
from ._health import LiveFibers, Recorder
from ._record import End, Start
from ._sampler import Sampler
from ._tls import Pem, self_signed
from ._workload import Workload, loop


@dataclass(frozen=True)
class Config:
    duration: float
    interval: float
    warmup: float
    rate: float
    """Scales every workload's pace: 2.0 runs operations twice as often."""
    stall_limit: float
    shutdown_limit: float
    out: Path
    work_dir: Path
    seed: int = 1


def _wait(stop: threading.Event, deadline: float) -> fx.Effect[None]:
    """Sleep in short steps until ``stop`` is set or ``deadline`` (monotonic) passes."""

    def step() -> fx.Effect[None]:
        if stop.is_set() or time.monotonic() >= deadline:
            return fx.void
        return fx.sleep("500 millis").and_then(fx.suspend(step))

    return fx.suspend(step)


def _layers(config: Config, pem: Pem) -> fx.Layer[Any, Any]:
    client = httpx_client.layer_with(
        verify=pem.client_context(),
        limits=httpx.Limits(max_connections=16, max_keepalive_connections=16, keepalive_expiry=2),
    )
    database = sqlite.layer(sqlite.SqliteClientConfig(filename=str(config.work_dir / "soak.db")))
    return layer.merge(_http.server_layer(pem), client, database)


@dataclass
class _State:
    config: Config
    sampler: Sampler
    recorders: dict[str, Recorder]
    stop: threading.Event
    stopped_at: list[float]


def _program(state: _State, pem: Pem) -> fx.Effect[None, Any]:
    config = state.config

    @fx.fn
    def main():
        server = yield from HttpServer()
        assert isinstance(server.address, InetAddressV4)
        base = f"https://localhost:{server.address.port}"
        client = yield from HttpClient()
        sql = yield from SqlClient()
        yield from sql.unsafe(_data.SCHEMA)
        resources = yield from _runtime.make_resources()
        semaphore = yield from _runtime.make_semaphore_workload()
        workloads: list[Workload] = [
            *_http.workloads(client, base),
            _http.websocket_workload(base),
            _runtime.fibers_workload,
            *resources,
            *_runtime.handoff_workloads,
            semaphore,
            *_data.data_workloads,
        ]
        loops: list[fx.Fiber[Any, Any]] = []
        for index, workload in enumerate(workloads):
            recorder = Recorder(workload.name, index + 1)
            state.recorders[workload.name] = recorder
            for n in range(workload.loops):
                seed = config.seed * 1_000_003 + index * 101 + n
                fiber = yield from loop(workload, recorder, seed, config.rate).fork()
                loops.append(fiber)
        state.sampler.start()
        yield from _wait(state.stop, time.monotonic() + config.duration)
        state.stopped_at.append(time.monotonic())
        state.stop.set()
        yield from fx.Fiber.interrupt_all(loops)

    return scoped(main().pipe(fx.provide(_http.app))).pipe(fx.provide(_layers(config, pem)))


def run(config: Config) -> End:
    config.work_dir.mkdir(parents=True, exist_ok=True)
    (config.work_dir / "soak.db").unlink(missing_ok=True)
    pem = self_signed(config.work_dir)
    # The websockets client verifies with the default context, which reads this.
    os.environ["SSL_CERT_FILE"] = str(pem.cert_path)

    fibers = LiveFibers()
    recorders: dict[str, Recorder] = {}
    sampler = Sampler(config.out, config.interval, config.stall_limit, recorders, fibers)
    state = _State(config, sampler, recorders, threading.Event(), [])

    def stop_on_signal(_signum: int, _frame: object) -> None:
        state.stop.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop_on_signal)

    sampler.write(
        Start(
            python=sys.version.split()[0],
            gil=getattr(sys, "_is_gil_enabled", lambda: True)(),
            duration=config.duration,
            interval=config.interval,
            warmup=config.warmup,
        )
    )
    done = threading.Event()
    watchdog = threading.Thread(
        target=_watchdog, args=(state.stop, done, sampler, config), daemon=True
    )
    watchdog.start()
    exit = fx.run_blocking_exit(
        _program(state, pem), context=Context.make(FiberRuntimeMetrics, fibers)
    )
    finished = time.monotonic()
    done.set()
    state.stop.set()
    sampler.stop()
    stopped = state.stopped_at[0] if state.stopped_at else finished
    # Fibers of other runs (the socket and httpx loops' callbacks) may end just after.
    deadline = time.monotonic() + 10
    while fibers.live and time.monotonic() < deadline:
        time.sleep(0.1)
    end = End(
        t=sampler.elapsed(),
        shutdown_seconds=finished - stopped,
        fibers_live=fibers.live,
        error=None if isinstance(exit, fx.Success) else exit.cause.pretty(),
    )
    sampler.write(end)
    sampler.close()
    return end


def _watchdog(
    stop: threading.Event, done: threading.Event, sampler: Sampler, config: Config
) -> None:
    """If the soak has not stopped ``shutdown_limit`` seconds after it was told to,
    record that with every thread's stack and exit."""
    stop.wait()
    if done.wait(config.shutdown_limit):
        return
    stacks = config.out.with_suffix(".stacks.txt")
    with stacks.open("w") as file:
        faulthandler.dump_traceback(file=file, all_threads=True)
    sampler.write(
        End(
            t=sampler.elapsed(),
            shutdown_seconds=None,
            fibers_live=sampler.sample().fibers_live,
            error=f"did not stop within {config.shutdown_limit}s; stacks in {stacks}",
        )
    )
    os._exit(3)
