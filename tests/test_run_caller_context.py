"""Every run entry point runs its effect in its caller's ``contextvars``.

Node's ``AsyncLocalStorage`` follows each caller of ``runPromise`` /
``runFork`` / ``runCallback`` / ``runSync``, on a ``ManagedRuntime`` as with
``Effect.runPromise`` (Effect 4.1.2 under Node: three concurrent
``als.run("r<i>", () => runtime.runPromise(prog))`` read r0, r1, r2, before
and after a sleep and in a forked child). In Python that is the caller's
``contextvars`` context: a request id set by one web request must never be
read by another request's effect.

The crossing happens where one caller's fiber is first run by someone else:
a scheduler shared between callers (a ``ManagedRuntime``'s, one asyncio loop's,
or one given to ``run_fork``) drained by another task or thread. Each case
below starts a run while another caller, with a context of its own, is
driving the same scheduler.

``test_every_run_entry_point_has_a_case`` finds the public run functions
(``pyfect.run_*`` and ``ManagedRuntime.run_*``), so a new one cannot skip
this test.
"""

from __future__ import annotations

import ast
import asyncio
import contextvars
import inspect
import threading
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import layer
from pyfect.http import asgi, server_response
from pyfect.http.asgi import Message, Scope
from pyfect.http.server_request import HttpServerRequest
from pyfect.scheduler import SyncScheduler

SRC = Path(__file__).parent.parent / "src" / "pyfect"
request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class Greeting(fx.Tag[str]): ...


def _runtime() -> fx.ManagedRuntime[Greeting]:
    return fx.ManagedRuntime.make(layer.succeed(Greeting, "hi"))


class Seen:
    """What one run read, thread-safely."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.values: list[str] = []
        self.done = threading.Event()

    def read(self) -> fx.Effect[None]:
        def record() -> None:
            with self._lock:
                self.values.append(request_id.get())

        return fx.sync(record)

    def finished(self) -> fx.Effect[None]:
        return fx.sync(self.done.set)


def waiting(seen: Seen) -> fx.Effect[None]:
    """Reads at the start, after a sleep, and in a scheduled (not started
    immediately) child."""

    @fx.gen
    def program():
        yield from seen.read()
        yield from fx.sleep("5 millis")
        yield from seen.read()
        child = yield from seen.read().fork()
        yield from child.join()
        yield from seen.finished()

    return program


def not_waiting(seen: Seen) -> fx.Effect[None]:
    return seen.read().and_then(seen.finished())


def _in_thread(value: str, f: Callable[[], object]) -> threading.Thread:
    def target() -> None:
        request_id.set(value)
        f()

    thread = threading.Thread(target=target)
    thread.start()
    return thread


def _while_another_thread_drives(
    drive: Callable[[fx.Effect[None]], object], call: Callable[[Seen], object], *, waits: bool
) -> list[str]:
    """``call`` made on a thread of its own while a thread with another
    context runs ``drive`` (a sync run sharing the scheduler) over a sleep."""
    driving = threading.Event()
    release = threading.Event()

    @fx.gen
    def driver():
        yield from fx.sync(driving.set)
        while not release.is_set():
            yield from fx.sleep("1 millis")

    driver_thread = _in_thread("driver", lambda: drive(driver))
    assert driving.wait(5)
    seen = Seen()
    caller = _in_thread("caller", lambda: call(seen))
    caller.join(5)
    assert seen.done.wait(5) or not waits
    release.set()
    driver_thread.join(5)
    assert seen.done.wait(5)
    return seen.values


def _expected(value: str, *, waits: bool) -> list[str]:
    return [value] * (3 if waits else 1)


# --- ManagedRuntime ---------------------------------------------------------------


def _managed_sync(name: str, *, waits: bool) -> None:
    runtime = _runtime()
    runtime.run_blocking(fx.void)
    entry = getattr(runtime, name)
    make = waiting if waits else not_waiting
    try:
        seen = _while_another_thread_drives(
            runtime.run_blocking, lambda s: entry(make(s)), waits=waits
        )
    finally:
        runtime.dispose()
    assert seen == _expected("caller", waits=waits)


def _managed_from_thread(name: str) -> None:
    """``run_fork`` / ``run_callback`` with no fiber and no loop: queued on
    the runtime's scheduler, which another thread is driving."""
    runtime = _runtime()
    runtime.run_blocking(fx.void)
    entry = getattr(runtime, name)
    try:
        seen = _while_another_thread_drives(
            runtime.run_blocking, lambda s: entry(waiting(s)), waits=True
        )
    finally:
        runtime.dispose()
    assert seen == _expected("caller", waits=True)


def _concurrent_tasks(start: Callable[[Seen], Coroutine[Any, Any, object]]) -> list[list[str]]:
    """Three asyncio tasks, each with its own request id, start at once."""

    async def main() -> list[list[str]]:
        async def call(i: int) -> list[str]:
            request_id.set(f"r{i}")
            seen = Seen()
            await start(seen)
            while not seen.done.is_set():
                await asyncio.sleep(0.001)
            return seen.values

        return await asyncio.gather(*(call(i) for i in range(3)))

    return asyncio.run(main())


def _managed_on_loop(name: str) -> None:
    """Every task on one loop shares the runtime's loop scheduler."""
    runtime = _runtime()

    async def start(seen: Seen) -> object:
        result = getattr(runtime, name)(waiting(seen))
        return await result if inspect.isawaitable(result) else result

    seen = _concurrent_tasks_on_one_loop(runtime, start)
    assert seen == [_expected(f"r{i}", waits=True) for i in range(3)]


def _concurrent_tasks_on_one_loop(
    runtime: fx.ManagedRuntime[Greeting], start: Callable[[Seen], Coroutine[Any, Any, object]]
) -> list[list[str]]:
    async def main() -> list[list[str]]:
        await runtime.run_async(fx.void)

        async def call(i: int) -> list[str]:
            request_id.set(f"r{i}")
            seen = Seen()
            await start(seen)
            while not seen.done.is_set():
                await asyncio.sleep(0.001)
            return seen.values

        try:
            return await asyncio.gather(*(call(i) for i in range(3)))
        finally:
            await runtime.dispose_async()

    return asyncio.run(main())


# --- pyfect.run_* -----------------------------------------------------------------


def _plain_sync(name: str, *, waits: bool) -> None:
    """Each thread's run has a scheduler of its own: no crossing possible,
    but checked all the same."""
    entry: Callable[[fx.Effect[None]], object] = getattr(fx, name)
    make = waiting if waits else not_waiting
    seen = _while_another_thread_drives(fx.run_blocking, lambda s: entry(make(s)), waits=waits)
    assert seen == _expected("caller", waits=waits)


def _plain_with_scheduler(name: str) -> None:
    """``run_fork`` / ``run_callback`` given a scheduler another thread drives."""
    shared = SyncScheduler()
    entry = getattr(fx, name)
    stop = threading.Event()

    def drive(eff: fx.Effect[None]) -> None:
        entry(eff, scheduler=shared)
        shared.run_until(stop.is_set)

    try:
        seen = _while_another_thread_drives(
            drive, lambda s: entry(waiting(s), scheduler=shared), waits=True
        )
    finally:
        stop.set()
        shared.schedule(lambda: None)
    assert seen == _expected("caller", waits=True)


def _plain_on_loop(name: str) -> None:
    async def start(seen: Seen) -> object:
        result = getattr(fx, name)(waiting(seen))
        return await result if inspect.isawaitable(result) else result

    seen = _concurrent_tasks(start)
    assert seen == [_expected(f"r{i}", waits=True) for i in range(3)]


def _run_main() -> None:
    """``run_main`` owns the loop it runs on; its effect reads the caller's
    context, as a coroutine passed to ``asyncio.run`` does."""
    seen = Seen()

    def main() -> None:
        request_id.set("caller")
        fx.run_main(waiting(seen))

    contextvars.Context().run(main)
    assert seen.values == _expected("caller", waits=True)


CASES: dict[str, Callable[[], None]] = {
    "ManagedRuntime.run_sync": lambda: _managed_sync("run_sync", waits=False),
    "ManagedRuntime.run_sync_exit": lambda: _managed_sync("run_sync_exit", waits=False),
    "ManagedRuntime.run_blocking": lambda: _managed_sync("run_blocking", waits=True),
    "ManagedRuntime.run_blocking_exit": lambda: _managed_sync("run_blocking_exit", waits=True),
    "ManagedRuntime.run_fork": lambda: _managed_from_thread("run_fork"),
    "ManagedRuntime.run_callback": lambda: _managed_from_thread("run_callback"),
    "ManagedRuntime.run_async": lambda: _managed_on_loop("run_async"),
    "ManagedRuntime.run_async_exit": lambda: _managed_on_loop("run_async_exit"),
    "ManagedRuntime.run_fork on a loop": lambda: _managed_on_loop("run_fork"),
    "ManagedRuntime.run_callback on a loop": lambda: _managed_on_loop("run_callback"),
    "run_sync": lambda: _plain_sync("run_sync", waits=False),
    "run_sync_exit": lambda: _plain_sync("run_sync_exit", waits=False),
    "run_blocking": lambda: _plain_sync("run_blocking", waits=True),
    "run_blocking_exit": lambda: _plain_sync("run_blocking_exit", waits=True),
    "run_fork": lambda: _plain_with_scheduler("run_fork"),
    "run_callback": lambda: _plain_with_scheduler("run_callback"),
    "run_async": lambda: _plain_on_loop("run_async"),
    "run_async_exit": lambda: _plain_on_loop("run_async_exit"),
    "run_fork on a loop": lambda: _plain_on_loop("run_fork"),
    "run_callback on a loop": lambda: _plain_on_loop("run_callback"),
    "run_main": _run_main,
}


@pytest.mark.parametrize("case", list(CASES))
def test_a_run_reads_its_callers_context(case: str) -> None:
    CASES[case]()


def test_every_run_entry_point_has_a_case() -> None:
    entry_points = {n for n in dir(fx) if n.startswith("run_")} | {
        f"ManagedRuntime.{n}" for n in dir(fx.ManagedRuntime) if n.startswith("run_")
    }
    assert entry_points <= set(CASES)


def test_a_forked_fiber_set_runner_reads_its_callers_context() -> None:
    """``FiberSet.runtime()``'s runner (Effect's ``runForkWith``), called
    from another thread while the run it forks into is busy elsewhere."""
    release = threading.Event()
    seen = Seen()

    @fx.gen
    def program():
        fibers = yield from fx.FiberSet[None, Never].make()
        runner = yield from fibers.runtime()
        caller = _in_thread("caller", lambda: runner(waiting(seen)))
        while not release.is_set():
            yield from fx.sleep("1 millis")
            if seen.done.is_set():
                release.set()
        caller.join(5)

    request_id.set("driver")
    fx.run_blocking(fx.scoped(program))
    assert seen.values == _expected("caller", waits=True)


def test_asgi_requests_read_their_own_context() -> None:
    """A host (FastAPI middleware, a request-id ASGI wrapper) sets a
    request-scoped ContextVar before calling the pyfect app: each request's
    handler, and a child it forks, reads its own."""

    @fx.gen
    def handle():
        yield from HttpServerRequest()
        first = request_id.get()
        yield from fx.sleep("5 millis")
        child = yield from fx.sync(request_id.get).fork()
        in_child = yield from child.join()
        return server_response.text(f"{first} {request_id.get()} {in_child}")

    app = asgi.to_asgi(handle, layer.succeed(Greeting, "hi"))

    async def request(i: int) -> bytes:
        request_id.set(f"r{i}")
        sent: list[Message] = []
        inbox = [{"type": "http.request", "body": b"", "more_body": False}]

        async def receive() -> Message:
            if inbox:
                return inbox.pop()
            await asyncio.Event().wait()  # the client never disconnects
            raise AssertionError("unreachable")

        async def send(message: Message) -> None:
            sent.append(message)

        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"test")],
            "client": ("10.0.0.1", 1234),
            "server": ("test", 80),
            "extensions": {},
        }
        await app(scope, receive, send)
        return b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")

    async def main() -> list[bytes]:
        try:
            return await asyncio.gather(*(request(i) for i in range(3)))
        finally:
            await app.runtime.dispose_async()

    assert asyncio.run(main()) == [f"r{i} r{i} r{i}".encode() for i in range(3)]


def test_a_sync_run_sets_its_callers_own_context() -> None:
    """``run_sync`` / ``run_blocking`` run the effect on the calling thread,
    before they return, as Effect's ``runSync`` evaluates it: a value the
    effect sets before it first waits is the caller's (Effect 4.1.2 under
    Node: ``als.enterWith("inner")`` in ``runSync`` is read by the caller)."""

    def sets(value: str) -> fx.Effect[None]:
        return fx.sync(lambda: request_id.set(value)).as_(None)

    def in_fresh_context(f: Callable[[], object]) -> str:
        def body() -> str:
            f()
            return request_id.get()

        return contextvars.Context().run(body)

    assert in_fresh_context(lambda: fx.run_sync(sets("sync"))) == "sync"
    assert in_fresh_context(lambda: fx.run_blocking(sets("blocking"))) == "blocking"


def _calls(attribute: str) -> list[str]:
    """Where ``src/pyfect`` calls ``Fiber``'s method ``attribute`` (modules
    with a method of their own by that name aside)."""
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        defines = any(
            isinstance(node, ast.FunctionDef) and node.name == attribute for node in ast.walk(tree)
        )
        if defines and path.name != "_fiber.py":
            continue
        found.extend(
            f"{path.relative_to(SRC)}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attribute
        )
    return found


def test_a_fibers_first_run_is_scheduled_only_through_start() -> None:
    """``Fiber._start`` is where a scheduled first run takes its starter's
    context. Nothing else may hand a fiber's run to a scheduler (``_drive``)
    or run it (``_drain``), and only the two run functions whose caller
    drives the scheduler at once skip the copy."""
    assert {c.split(":")[0] for c in _calls("_drive") + _calls("_drain")} == {"_fiber.py"}
    skipping = [
        f"{path.relative_to(SRC)}:{node.lineno}"
        for path in sorted(SRC.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.keyword) and node.arg == "caller_drives"
    ]
    assert len(skipping) == 2
    assert {s.split(":")[0] for s in skipping} == {"run.py"}
