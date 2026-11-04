"""Exceptions that are not ``Exception`` raised by user code.

Effect makes anything thrown inside an effect a defect. Python also raises
``BaseException`` subclasses that are not errors of the program:
``SystemExit`` (``sys.exit``), ``asyncio.CancelledError``,
``GeneratorExit``, a custom ``BaseException``. Each is a defect where it
happens, so finalizers run and ``catch_defect`` sees it. Ctrl-C is the
exception: the step it cuts short ends as interrupted and the runner
interrupts the main fiber, then re-raises ``KeyboardInterrupt`` (``run_sync``)
or ends the process with 130 (``run_main``), as when Ctrl-C lands while every
fiber is parked.
"""

import ast
import asyncio
import signal
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Never

import pytest

import pyfect as fx


class _Custom(BaseException):
    pass


def _system_exit() -> BaseException:
    return SystemExit(3)


def _cancelled() -> BaseException:
    return asyncio.CancelledError()


def _generator_exit() -> BaseException:
    return GeneratorExit()


def _custom() -> BaseException:
    return _Custom()


KINDS: list[Callable[[], BaseException]] = [_system_exit, _cancelled, _generator_exit, _custom]


def _raise(exc: BaseException) -> Never:
    raise exc


def _from_sync(exc: BaseException) -> fx.Effect[object]:
    return fx.sync(lambda: _raise(exc))


def _from_map(exc: BaseException) -> fx.Effect[object]:
    return fx.succeed(1).map(lambda _: _raise(exc))


def _from_flat_map(exc: BaseException) -> fx.Effect[object]:
    return fx.succeed(1).flat_map(lambda _: _raise(exc))


def _from_gen(exc: BaseException) -> fx.Effect[object]:
    @fx.gen
    def body():
        yield from fx.succeed(1)
        _raise(exc)

    return body


def _from_callback_register(exc: BaseException) -> fx.Effect[object]:
    return fx.callback(lambda resume: _raise(exc))


def _from_catch_handler(exc: BaseException) -> fx.Effect[object]:
    return fx.fail("e").catch_all(lambda _: _raise(exc))


def _from_release(exc: BaseException) -> fx.Effect[object]:
    return fx.scoped(fx.acquire_release(fx.succeed(1), lambda a, ex: _raise(exc)))


def _from_child(exc: BaseException) -> fx.Effect[object]:
    return fx.sync(lambda: _raise(exc)).fork().flat_map(lambda f: f.join())


PLACES: list[Callable[[BaseException], fx.Effect[object]]] = [
    _from_sync,
    _from_map,
    _from_flat_map,
    _from_gen,
    _from_callback_register,
    _from_catch_handler,
    _from_release,
    _from_child,
]


def _died_with(ex: fx.Exit[Any, Any], exc: BaseException) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.find_defect() is exc


@pytest.mark.parametrize("place", PLACES, ids=lambda p: p.__name__)
@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.__name__)
def test_a_base_exception_from_user_code_is_a_defect_and_finalizers_run(
    kind: Callable[[], BaseException], place: Callable[[BaseException], fx.Effect[object]]
):
    exc = kind()
    log: list[str] = []
    ex = fx.run_sync_exit(place(exc).ensuring(fx.sync(lambda: log.append("fin"))))
    assert _died_with(ex, exc)
    assert log == ["fin"]


@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.__name__)
def test_catch_defect_sees_a_base_exception(kind: Callable[[], BaseException]):
    exc = kind()
    caught = _from_sync(exc).catch_defect(fx.succeed)
    assert fx.run_sync(caught) is exc


@pytest.mark.parametrize("kind", KINDS, ids=lambda k: k.__name__)
def test_a_base_exception_under_run_async_is_a_defect_not_a_hang(
    kind: Callable[[], BaseException],
):
    exc = kind()
    log: list[str] = []
    prog = _from_sync(exc).ensuring(fx.sync(lambda: log.append("fin")))

    async def main() -> fx.Exit[object, Never]:
        return await asyncio.wait_for(fx.run_async_exit(prog), 5)

    assert _died_with(asyncio.run(main()), exc)
    assert log == ["fin"]


@pytest.mark.parametrize("kind", [_system_exit, _generator_exit, _custom], ids=lambda k: k.__name__)
def test_a_base_exception_from_an_awaited_coroutine_is_a_defect(
    kind: Callable[[], BaseException],
):
    """asyncio re-raises ``SystemExit`` out of the loop; under ``from_async``
    it is a defect of the fiber like any other raise."""
    exc = kind()
    log: list[str] = []

    async def body() -> None:
        await asyncio.sleep(0)
        raise exc

    prog = fx.from_async(body).ensuring(fx.sync(lambda: log.append("fin")))

    async def main() -> fx.Exit[object, Never]:
        return await asyncio.wait_for(fx.run_async_exit(prog), 5)

    assert _died_with(asyncio.run(main()), exc)
    assert log == ["fin"]


# A ``GeneratorExit`` raised while closing is Python's way to end the close.
@pytest.mark.parametrize("kind", [_system_exit, _cancelled, _custom], ids=lambda k: k.__name__)
def test_a_base_exception_from_a_generator_closing_on_failure_keeps_the_failure(
    kind: Callable[[], BaseException],
):
    """The same cause as when the ``finally`` raises an ``Exception``: the
    failure merged with the defect."""

    def closing_with(exc: BaseException) -> fx.Effect[object, str]:
        @fx.gen
        def body():
            try:
                yield from fx.fail("boom")
            finally:
                _raise(exc)

        return body

    exc = kind()
    ex = fx.run_sync_exit(closing_with(exc))
    plain = fx.run_sync_exit(closing_with(ValueError()))
    assert isinstance(ex, fx.Failure) and isinstance(plain, fx.Failure)
    assert repr(ex.cause.reasons[:-1]) == repr(plain.cause.reasons[:-1])
    assert ex.cause.reasons[-1] == fx.cause.Die(exc)


def test_run_sync_raises_a_system_exit_after_the_finalizers():
    log: list[str] = []
    prog = fx.sync(lambda: sys.exit(3)).ensuring(fx.sync(lambda: log.append("fin")))
    with pytest.raises(SystemExit) as raised:
        fx.run_sync(prog)
    assert raised.value.code == 3
    assert log == ["fin"]


def test_sys_exit_under_run_main_exits_with_its_status_after_the_finalizers(
    capsys: pytest.CaptureFixture[str],
):
    log: list[str] = []
    prog = fx.sync(lambda: sys.exit(3)).ensuring(fx.sync(lambda: log.append("fin")))
    with pytest.raises(SystemExit) as raised:
        fx.run_main(prog)
    assert raised.value.code == 3
    assert log == ["fin"]
    assert "ERROR" not in capsys.readouterr().out


# --- Ctrl-C -------------------------------------------------------------------


def _ctrl_c() -> Never:
    raise KeyboardInterrupt


def test_ctrl_c_in_user_code_interrupts_the_run_and_runs_finalizers():
    log: list[str] = []
    prog = fx.sync(_ctrl_c).ensuring(fx.sync(lambda: log.append("fin")))
    with pytest.raises(KeyboardInterrupt):
        fx.run_sync(prog)
    assert log == ["fin"]


def test_ctrl_c_is_not_a_defect_that_catch_defect_can_swallow():
    log: list[str] = []
    prog = (
        fx.sync(_ctrl_c)
        .catch_defect(lambda d: fx.sync(lambda: log.append("caught")))
        .ensuring(fx.sync(lambda: log.append("fin")))
    )
    with pytest.raises(KeyboardInterrupt):
        fx.run_sync(prog)
    assert log == ["fin"]


def test_ctrl_c_in_a_child_interrupts_the_main_fiber_and_both_finalize():
    log: list[str] = []

    @fx.gen
    def prog():
        child = (
            fx.sleep(0.01)
            .and_then(fx.sync(_ctrl_c))
            .ensuring(fx.sync(lambda: log.append("child fin")))
        )
        yield from child.fork()
        yield from fx.never.ensuring(fx.sync(lambda: log.append("main fin")))

    with pytest.raises(KeyboardInterrupt):
        fx.run_sync(prog)
    assert sorted(log) == ["child fin", "main fin"]


def test_ctrl_c_loses_no_fiber_queued_behind_the_one_it_hit():
    """The fibers that were due in the same scheduler turn still run."""
    log: list[str] = []

    @fx.gen
    def prog():
        yield from fx.sync(_ctrl_c).fork()
        yield from fx.sync(lambda: log.append("sibling ran")).fork()
        yield from fx.never.ensuring(fx.sync(lambda: log.append("main fin")))

    with pytest.raises(KeyboardInterrupt):
        fx.run_sync(prog)
    assert log == ["sibling ran", "main fin"]


@pytest.mark.skipif(
    threading.current_thread() is not threading.main_thread(), reason="signals go to main"
)
def test_a_real_sigint_during_blocking_user_code_runs_the_finalizers():
    """The signal goes to the main thread once the user code has started:
    a timer racing the run, or a SIGINT the OS hands to the sending thread
    (which leaves the main thread's sleep running), made this flaky under
    load."""
    log: list[str] = []
    blocking = threading.Event()

    def block() -> None:
        blocking.set()
        time.sleep(30)

    def send() -> None:
        if blocking.wait(30):
            signal.pthread_kill(threading.main_thread().ident or 0, signal.SIGINT)

    prog = fx.sync(block).ensuring(fx.sync(lambda: log.append("fin")))
    started = time.monotonic()
    sender = threading.Thread(target=send, daemon=True)
    sender.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            fx.run_sync(prog)
    finally:
        sender.join()
    assert log == ["fin"]
    assert time.monotonic() - started < 30


def test_ctrl_c_making_an_awaitable_is_not_a_defect():
    """``from_async`` calls ``make`` on the fiber; Ctrl-C there interrupts
    the run as in ``sync``, rather than becoming a catchable defect."""
    log: list[str] = []

    def make() -> Any:
        _ctrl_c()

    prog = (
        fx.from_async(make)
        .catch_defect(lambda d: fx.sync(lambda: log.append("caught")))
        .ensuring(fx.sync(lambda: log.append("fin")))
    )

    async def main() -> object:
        return await fx.run_async(prog)

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(main())
    assert log == ["fin"]


def test_ctrl_c_in_an_rpc_handler_is_not_a_defect_of_the_request():
    from pyfect import schema as S
    from pyfect.rpc import RpcGroup, make
    from pyfect.rpc import client as rpc_client
    from pyfect.rpc import server as rpc_server
    from pyfect.rpc.client import ClientOptions

    class Echo(RpcGroup):
        ping = make("Ping", success=S.String)

    log: list[str] = []

    def body():
        cores: list[rpc_client.ClientCore] = []
        server = yield from rpc_server.make_no_serialization(
            Echo,
            lambda response: cores[0].write(response),  # noqa: PLW0108 (made below)
        )
        client, core = yield from rpc_client.make_no_serialization(
            Echo, lambda sent: server.write(0, sent.message), ClientOptions()
        )
        cores.append(core)
        return (yield from client.ping())

    handlers = Echo.to_layer(Echo.handlers().handle(Echo.ping)(lambda _: _ctrl_c()))
    prog = (
        fx.scoped(fx.gen(body))
        .pipe(fx.provide(handlers))
        .catch_defect(lambda d: fx.sync(lambda: log.append("caught")))
        .ensuring(fx.sync(lambda: log.append("fin")))
    )
    with pytest.raises(KeyboardInterrupt):
        fx.run_sync(prog.timeout(5).or_die())
    assert log == ["fin"]


def test_ctrl_c_in_user_code_under_run_main_exits_130_after_the_finalizers():
    log: list[str] = []
    prog = fx.sync(_ctrl_c).ensuring(fx.sync(lambda: log.append("fin")))
    with pytest.raises(SystemExit) as raised:
        fx.run_main(prog)
    assert raised.value.code == 130
    assert log == ["fin"]


# --- exit observers -----------------------------------------------------------


def test_a_raising_exit_observer_does_not_keep_the_exit_from_the_others():
    seen: list[fx.Exit[int, Never]] = []

    async def main() -> int:
        fiber = fx.run_fork(fx.sleep(0.01).as_(42))
        fiber.add_observer_unsafe(lambda ex: _raise(ZeroDivisionError()))
        fiber.add_observer_unsafe(seen.append)
        return await asyncio.wait_for(fx.run_async(fiber.join()), 5)

    loop = asyncio.new_event_loop()
    errors: list[object] = []
    loop.set_exception_handler(lambda _, context: errors.append(context.get("exception")))
    try:
        assert loop.run_until_complete(main()) == 42
    finally:
        loop.close()
    assert seen == [fx.Success(42)]
    assert any(isinstance(e, ZeroDivisionError) for e in errors)


# --- guard --------------------------------------------------------------------

_SRC = Path(__file__).parent.parent / "src" / "pyfect"
# How the fiber runtime calls into user code: a primitive's step, a
# continuation frame, the tracer hook around them, a callback's register
# function, an exit observer.
_USER_CALLS = {"_step", "_on_success", "_on_failure", "hook", "register", "observer"}
# Public calls that run user code on the caller's own stack, outside any
# fiber, so a raise goes straight back to that caller.
_CALLERS_STACK = {"add_observer_unsafe"}


def _catches_base_exception(handler: ast.ExceptHandler) -> bool:
    return isinstance(handler.type, ast.Name) and handler.type.id == "BaseException"


def test_the_fiber_runtime_calls_user_code_only_where_base_exceptions_are_caught():
    """A ``try`` that catches only ``Exception`` around user code is how a
    ``SystemExit`` or a Ctrl-C escaped the loop and lost the fiber's step.
    Every call into user code in ``_fiber.py`` sits in a ``try`` that
    catches ``BaseException`` (directly, or in a helper referenced only from
    such a ``try``), and the loop's handlers go through ``Fiber._raised``."""
    tree = ast.parse((_SRC / "_fiber.py").read_text())
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def guarded(node: ast.AST) -> bool:
        while node in parents:
            parent = parents[node]
            if (
                isinstance(parent, ast.Try)
                and node in parent.body
                and any(_catches_base_exception(h) for h in parent.handlers)
            ):
                return True
            node = parent
        return False

    def enclosing_function(node: ast.AST) -> ast.FunctionDef | None:
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.FunctionDef):
                return node
        return None

    module_functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}

    def reached_only_guarded(name: str) -> bool:
        uses = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)
        ]
        return bool(uses) and all(guarded(u) for u in uses)

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in _USER_CALLS or guarded(node):
            continue
        owner = enclosing_function(node)
        if owner is not None and (
            owner.name in _CALLERS_STACK
            or (owner.name in module_functions and reached_only_guarded(owner.name))
        ):
            continue
        offenders.append(f"{name} at line {node.lineno}")
    assert offenders == []

    loop_handlers = [
        h
        for f in ast.walk(tree)
        if isinstance(f, ast.FunctionDef) and f.name in {"_loop", "_continue"}
        for h in ast.walk(f)
        if isinstance(h, ast.ExceptHandler)
    ]
    assert loop_handlers
    for handler in loop_handlers:
        assert _catches_base_exception(handler)
        calls = {
            n.func.attr
            for n in ast.walk(handler)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "_raised" in calls


def test_no_bare_exception_handler_in_the_runtime_core():
    """``except Exception`` in the loop or the schedulers lets every other
    ``BaseException`` skip the fiber's bookkeeping."""
    offenders = [
        f"{name}:{h.lineno}"
        for name in (
            "_fiber.py",
            "scheduler.py",
            "run.py",
            "_core.py",
            "_primitives.py",
            "_effect_resources.py",
            "_concurrency.py",
            "scope.py",
        )
        for h in ast.walk(ast.parse((_SRC / name).read_text()))
        if isinstance(h, ast.ExceptHandler)
        and isinstance(h.type, ast.Name)
        and h.type.id == "Exception"
    ]
    assert offenders == []


# Code that never runs on a fiber's thread (worker threads, a driver's own
# loop thread), where Ctrl-C is never delivered.
_OFF_FIBER = {"workers/_thread.py", "sql/sqlite/_worker.py", "sql/_loop.py"}


def _names(node: ast.expr | None) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Tuple):
        return {e.id for e in node.elts if isinstance(e, ast.Name)}
    return set()


def test_no_handler_turns_ctrl_c_into_a_defect():
    """``except BaseException`` around user code also catches Ctrl-C; made
    into a defect, ``catch_defect`` could swallow it and the run would go
    on. Such a handler re-raises, or lets ``KeyboardInterrupt`` through
    first (``except KeyboardInterrupt: raise``), so the loop's
    ``Fiber._raised`` interrupts the fiber."""
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        name = path.relative_to(_SRC).as_posix()
        if name in _OFF_FIBER:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Try):
                continue
            ctrl_c_first = False
            for handler in node.handlers:
                caught = _names(handler.type)
                if "KeyboardInterrupt" in caught:
                    ctrl_c_first = True
                if "BaseException" not in caught or ctrl_c_first:
                    continue
                inside = list(ast.walk(handler))
                reraises = any(isinstance(n, ast.Raise) for n in inside)
                via_loop = any(isinstance(n, ast.Attribute) and n.attr == "_raised" for n in inside)
                if not (reraises or via_loop):
                    offenders.append(f"{name}:{handler.lineno}")
    # _finish raises the first observer's exception after the rest ran.
    assert offenders == ["_fiber.py:" + str(_finish_handler_line())]


def _finish_handler_line() -> int:
    tree = ast.parse((_SRC / "_fiber.py").read_text())
    (finish,) = [
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_finish"
    ]
    (handler,) = [n for n in ast.walk(finish) if isinstance(n, ast.ExceptHandler)]
    return handler.lineno
