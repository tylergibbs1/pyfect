"""``layer_fixture``: build a layer once per pytest scope and share it."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING, Literal, final

from pyfect.clock import Clock
from pyfect.context import Context
from pyfect.duration import Duration, to_seconds
from pyfect.exit import Success
from pyfect.layer import Layer
from pyfect.run import _unwrap
from pyfect.scope import CloseableScope
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
    import pytest

    limit = None if timeout is None else to_seconds(timeout)

    def fixture() -> Generator[Services[RO]]:
        runtime: Runtime = AsyncioRuntime() if asyncio else SyncRuntime()
        clock = None if live else TestClock(warning_delay=warning_delay)
        context = Context.empty() if clock is None else Context.empty().add(Clock, clock)
        resources = CloseableScope()
        try:
            built = _unwrap(runtime.run(layer.build(resources), context, timeout=limit))
            yield Services(context.merge(built), runtime)
        finally:
            closed = runtime.run(resources.close(Success(None)), context, timeout=limit)
            if clock is not None:
                clock.stop_warning()
            runtime.close()
            _unwrap(closed)

    return pytest.fixture(scope=scope)(fixture)
