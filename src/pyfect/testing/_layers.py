"""``layer_fixture`` / ``effect_fixture``: build a layer or run a scoped
effect once per pytest scope and share the result."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal, Never, final

from pyfect._effect_args import require_effect
from pyfect._layer_core import require_layer
from pyfect.clock import Clock
from pyfect.context import Context
from pyfect.duration import Duration, to_seconds
from pyfect.effect import Effect, provide_service
from pyfect.exit import Success
from pyfect.layer import Layer
from pyfect.run import unwrap
from pyfect.scope import CloseableScope, Scope
from pyfect.testing._clock import TestClock
from pyfect.testing._runtime import AsyncioRuntime, Runtime, SyncRuntime

if TYPE_CHECKING:
    from _pytest.fixtures import FixtureFunctionDefinition

type FixtureScope = Literal["function", "class", "module", "package", "session"]


@final
class Services[RO]:
    """The services a ``layer_fixture`` built, and the runtime they live on.

    Take it as the first parameter of an ``@effect`` test, annotated with
    what the layer builds; the test may then use those services::

        db = layer_fixture(DatabaseLive)

        @effect
        def test_query(db: Services[Database]):
            conn = yield from Database()
    """

    __slots__ = ("context", "runtime")

    def __init__(self, context: Context, runtime: Runtime) -> None:
        self.context = context
        self.runtime = runtime


def layer_fixture[RO, E](
    layer: Layer[RO, E],
    *,
    scope: FixtureScope = "module",
    live: bool = False,
    asyncio: bool = False,
    warning_delay: Duration = 1.0,
    timeout: Duration | None = None,
) -> FixtureFunctionDefinition:
    """A pytest fixture that builds ``layer`` once per ``scope`` and
    releases its resources when the scope ends.

    The layer is built with a ``TestClock`` (shared by every test that uses
    the fixture), unless ``live``: then it and its ``effect`` tests use the
    live clock. Tests using the fixture run on the
    fixture's runtime, so fibers the layer forks keep running; ``asyncio``
    picks an event loop for it, needed by ``from_async``. ``timeout``
    bounds building and releasing, in real time."""
    require_layer(layer, "layer")

    def fixture() -> Generator[Services[RO]]:
        with _held(
            layer.build_with_scope,
            live=live,
            asyncio=asyncio,
            warning_delay=warning_delay,
            timeout=timeout,
        ) as (built, context, runtime):
            yield Services(context.merge(built), runtime)

    return _fixture(fixture, scope)


def effect_fixture[A, E](
    eff: Effect[A, E, Scope],
    *,
    scope: FixtureScope = "function",
    live: bool = False,
    asyncio: bool = False,
    warning_delay: Duration = 1.0,
    timeout: Duration | None = None,
) -> FixtureFunctionDefinition:
    """A pytest fixture whose value is what ``eff`` succeeds with, run once
    per ``scope``. Finalizers ``eff`` adds to its ``Scope`` run when the
    scope ends; a failure is raised as the fixture's error.

    The options are ``layer_fixture``'s. The value is a plain Python value,
    so any test can take it; to share services or forked fibers with
    ``effect`` tests, use ``layer_fixture``."""
    require_effect(eff, "eff")

    def fixture() -> Generator[A]:
        with _held(
            lambda resources: eff.pipe(provide_service(Scope, resources)),
            live=live,
            asyncio=asyncio,
            warning_delay=warning_delay,
            timeout=timeout,
        ) as (value, _context, _runtime):
            yield value

    return _fixture(fixture, scope)


def _fixture(
    fixture: Callable[[], Generator[Any]], scope: FixtureScope
) -> FixtureFunctionDefinition:
    import pytest

    return pytest.fixture(scope=scope)(fixture)


@contextmanager
def _held[T](
    build: Callable[[CloseableScope], Effect[T, Any, Never]],
    *,
    live: bool,
    asyncio: bool,
    warning_delay: Duration,
    timeout: Duration | None,
) -> Generator[tuple[T, Context, Runtime]]:
    """Run ``build`` on a fresh runtime and clock, hold what it built, then
    close its scope and the runtime."""
    limit = None if timeout is None else to_seconds(timeout)
    runtime: Runtime = AsyncioRuntime() if asyncio else SyncRuntime()
    clock = None if live else TestClock(warning_delay=warning_delay)
    context = Context.empty() if clock is None else Context.empty().add(Clock, clock)
    resources = CloseableScope()
    try:
        built = unwrap(runtime.run(build(resources), context, timeout=limit))
        yield built, context, runtime
    finally:
        closed = runtime.run(resources.close(Success(None)), context, timeout=limit)
        if clock is not None:
            clock.stop_warning()
        runtime.close()
        unwrap(closed)
