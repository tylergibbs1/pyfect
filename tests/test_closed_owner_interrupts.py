"""Using a ``FiberMap``, ``FiberSet``, ``FiberHandle``, ``Scope``, ``Pool`` or
RPC client after it closed interrupts, as in Effect, and the interruption
names what was closed (DOGFOOD beacon 11, trawl 1 and 2): every way of
putting a fiber into one."""

from collections.abc import Callable
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import exit, scope
from pyfect import schema as S
from pyfect.cause import Interrupted
from pyfect.exit import Exit, Failure
from pyfect.fiber_handle import FiberHandle
from pyfect.fiber_map import FiberMap
from pyfect.fiber_set import FiberSet
from pyfect.pool import Pool
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import test as rpc_test
from pyfect.scoped_ref import ScopedRef

type _Use = Callable[[Any], fx.Effect[Exit[Any, Any]]]


def _closed[T](make: fx.Effect[T, Any, scope.Scope]) -> fx.Effect[T]:
    """``make`` in a scope that has closed."""
    return scope.scoped(make)


def _join(fiber: fx.Fiber[Any, Any]) -> fx.Effect[Exit[Any, Any]]:
    return fiber.await_exit()


def _via_runtime(owner: Any, *key: str) -> fx.Effect[Exit[Any, Any]]:
    """Fork through ``owner.runtime()``, the runner a callback outside the
    fiber uses."""
    runtime: fx.Effect[Callable[..., fx.Fiber[Any, Any]]] = owner.runtime()
    return runtime.flat_map(lambda run: _join(run(*key, fx.never)))


def _forked(add: Callable[[fx.Fiber[Any, Any]], fx.Effect[None]]) -> fx.Effect[Exit[Any, Any]]:
    @fx.fn
    def run():
        fiber = yield from fx.never.fork()
        yield from add(fiber)
        return (yield from fiber.await_exit())

    return run()


class Calls(RpcGroup):
    ping = make("Ping", success=S.String)
    ticks = make("Ticks", success=S.Int, stream=True)


CallsLive = Calls.to_layer(
    Calls.handlers()
    .handle(Calls.ping)(lambda _r: fx.succeed("pong"))
    .handle(Calls.ticks)(lambda _r: fx.stream.make(1, 2))
)


CASES: list[tuple[str, fx.Effect[Any, Any, scope.Scope], _Use]] = [
    ("FiberMap", FiberMap[str, None, Any].make(), lambda m: m.run("k", fx.never).exit()),
    (
        "FiberMap",
        FiberMap[str, None, Any].make(),
        lambda m: _forked(lambda f: fx.sync(lambda: m.set_unsafe("k", f))),
    ),
    (
        "FiberMap",
        FiberMap[str, None, Any].make(),
        lambda m: _via_runtime(m, "k"),
    ),
    ("FiberSet", FiberSet[None, Any].make(), lambda s: s.run(fx.never).flat_map(_join)),
    ("FiberSet", FiberSet[None, Any].make(), lambda s: _forked(s.add)),
    (
        "FiberSet",
        FiberSet[None, Any].make(),
        _via_runtime,
    ),
    ("FiberHandle", FiberHandle[None, Any].make(), lambda h: h.run(fx.never).exit()),
    ("FiberHandle", FiberHandle[None, Any].make(), lambda h: _forked(h.set)),
    (
        "FiberHandle",
        FiberHandle[None, Any].make(),
        _via_runtime,
    ),
    ("Scope", scope.Scope(), lambda s: scope.fork_in(fx.never, s).flat_map(_join)),
    ("Scope", scope.Scope(), lambda s: _forked(lambda f: fx.sync(lambda: f.run_in(s)).as_void())),
    ("Pool", Pool.make(fx.succeed(1), size=1), lambda p: scope.scoped(p.get()).exit()),
    (
        "RPC client",
        rpc_test.make_client(Calls, layer=CallsLive),
        lambda c: c.ping().exit(),
    ),
    (
        "RPC client",
        rpc_test.make_client(Calls, layer=CallsLive),
        lambda c: c.ticks().run_collect().exit(),
    ),
]


@pytest.mark.parametrize(
    ("owner", "make", "use"), CASES, ids=[f"{owner}-{i}" for i, (owner, _, _) in enumerate(CASES)]
)
def test_using_a_closed_owner_interrupts_and_names_it(
    owner: str, make: fx.Effect[Any, Any, scope.Scope], use: _Use
) -> None:
    exit_ = fx.run_sync(_closed(make).flat_map(use))
    assert isinstance(exit_, Failure)
    assert exit_.cause.has_interrupts_only
    error = exit_.cause.squash()
    assert isinstance(error, Interrupted)
    assert f"because the {owner} is closed" in "\n".join(error.__notes__)


def test_an_open_owner_interrupts_without_a_reason() -> None:
    @fx.fn
    def program():
        fiber_map = yield from FiberMap[str, None, Any].make()
        fiber = yield from fiber_map.run("k", fx.never)
        yield from fiber_map.remove("k")
        return (yield from fiber.await_exit())

    exit_ = fx.run_sync(scope.scoped(program()))
    assert isinstance(exit_, Failure)
    assert "because" not in "\n".join(exit_.cause.squash().__notes__)


def test_a_scoped_ref_whose_generation_closed_while_acquiring_names_the_scope() -> None:
    def close_own_scope() -> fx.Effect[int, Never, scope.Scope]:
        return scope.Scope().flat_map(lambda s: s.close(exit.succeed(None))).as_(1)

    @fx.fn
    def program():
        ref = yield from ScopedRef.make(lambda: 0)
        return (yield from ref.set(close_own_scope()).exit())

    for made in (ScopedRef.from_acquire(close_own_scope()).exit(), scope.scoped(program())):
        exit_ = fx.run_sync(scope.scoped(made))
        assert isinstance(exit_, Failure)
        assert "because the Scope is closed" in "\n".join(exit_.cause.squash().__notes__)
