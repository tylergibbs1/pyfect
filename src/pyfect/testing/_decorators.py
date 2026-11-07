"""``@effect`` and ``@live``: pytest tests written as effects."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import functools
from collections.abc import Callable, Generator
from typing import Any, Concatenate, Literal, overload

from pyfect._core import Effect, _Gen, _Suspend
from pyfect.clock import Clock, LiveClock
from pyfect.console import CurrentConsole
from pyfect.context import Context
from pyfect.duration import Duration, Seconds, to_seconds
from pyfect.run import unwrap
from pyfect.scope import Scope, scoped
from pyfect.testing._clock import TestClock
from pyfect.testing._console import TestConsole
from pyfect.testing._layers import Services
from pyfect.testing._runtime import AsyncioRuntime, Runtime, SyncRuntime

type TestBody[R] = Generator[Effect[Any, Any, R], Any, object] | Effect[object, object, R]
"""What a test function gives: a generator of effects (``yield from``), or
an effect. Any typed error fails the test."""


class Settings:
    """Defaults the pytest plugin reads from the ini file."""

    timeout: Seconds | None = Seconds(5.0)


settings = Settings()

type _Mode = Literal["effect", "live"]


class _Options:
    __slots__ = ("asyncio", "mode", "timeout", "warning_delay")

    def __init__(
        self, mode: _Mode, timeout: Duration | None, asyncio: bool, warning_delay: Duration
    ) -> None:
        self.mode: _Mode = mode
        self.timeout = None if timeout is None else to_seconds(timeout)
        self.asyncio = asyncio
        self.warning_delay = warning_delay


class TestDecorator:
    """``@effect(...)`` / ``@live(...)`` with options."""

    __test__ = False
    __slots__ = ("_options",)

    def __init__(self, options: _Options) -> None:
        self._options = options

    @overload
    def __call__[RO, **P](
        self, f: Callable[Concatenate[Services[RO], P], TestBody[RO | Scope]], /
    ) -> Callable[Concatenate[Services[RO], P], None]: ...
    @overload
    def __call__[S, RO, **P](
        self, f: Callable[Concatenate[S, Services[RO], P], TestBody[RO | Scope]], /
    ) -> Callable[Concatenate[S, Services[RO], P], None]: ...
    @overload
    def __call__[**P](self, f: Callable[P, TestBody[Scope]], /) -> Callable[P, None]: ...
    def __call__(self, f: Callable[..., Any], /) -> Callable[..., None]:
        return _make_test(f, self._options)


@overload
def effect[RO, **P](
    f: Callable[Concatenate[Services[RO], P], TestBody[RO | Scope]], /
) -> Callable[Concatenate[Services[RO], P], None]: ...
@overload
def effect[S, RO, **P](
    f: Callable[Concatenate[S, Services[RO], P], TestBody[RO | Scope]], /
) -> Callable[Concatenate[S, Services[RO], P], None]: ...
@overload
def effect[**P](f: Callable[P, TestBody[Scope]], /) -> Callable[P, None]: ...
@overload
def effect(
    *, timeout: Duration | None = None, asyncio: bool = False, warning_delay: Duration = "1 second"
) -> TestDecorator: ...
def effect(
    f: Callable[..., Any] | None = None,
    /,
    *,
    timeout: Duration | None = None,
    asyncio: bool = False,
    warning_delay: Duration = "1 second",
) -> Any:
    """A pytest test written as an effect, run with a ``TestClock``, a
    ``TestConsole`` and a ``Scope`` (closed when the test ends)::

        @effect
        def test_retries():
            fiber = yield from flaky_call.retry(spaced(1)).fork()
            yield from adjust(3)
            assert (yield from fiber.join()) == "ok"

    ``timeout`` (real time; default from the ``pyfect_timeout`` ini option)
    interrupts the test and runs its finalizers. ``asyncio`` runs it on an
    event loop, for ``from_async``. A first parameter annotated
    ``Services[...]`` (a ``layer_fixture``; in a test class, the parameter
    after ``self``) provides those services."""
    decorator = TestDecorator(_Options("effect", timeout, asyncio, warning_delay))
    return decorator if f is None else decorator(f)


@overload
def live[RO, **P](
    f: Callable[Concatenate[Services[RO], P], TestBody[RO | Scope]], /
) -> Callable[Concatenate[Services[RO], P], None]: ...
@overload
def live[S, RO, **P](
    f: Callable[Concatenate[S, Services[RO], P], TestBody[RO | Scope]], /
) -> Callable[Concatenate[S, Services[RO], P], None]: ...
@overload
def live[**P](f: Callable[P, TestBody[Scope]], /) -> Callable[P, None]: ...
@overload
def live(*, timeout: Duration | None = None, asyncio: bool = False) -> TestDecorator: ...
def live(
    f: Callable[..., Any] | None = None,
    /,
    *,
    timeout: Duration | None = None,
    asyncio: bool = False,
) -> Any:
    """Like ``effect``, but with the live clock and console: sleeps take
    real time and output is written."""
    decorator = TestDecorator(_Options("live", timeout, asyncio, "1 second"))
    return decorator if f is None else decorator(f)


def _make_test(f: Callable[..., Any], options: _Options) -> Callable[..., None]:
    import pytest

    @functools.wraps(f)
    def test(*args: Any, **kwargs: Any) -> None:
        services = _services_in(args, kwargs)
        runtime = _runtime_for(services, options)
        context, clock = _context_for(services, options)
        timeout = options.timeout if options.timeout is not None else settings.timeout
        try:
            ex = runtime.run(scoped(_body(f, args, kwargs)), context, timeout=timeout)
        finally:
            if clock is not None:
                clock.stop_warning()
            if services is None:
                runtime.close()
        unwrap(ex)

    marker = pytest.mark.pyfect_live if options.mode == "live" else pytest.mark.pyfect_effect
    return marker(test)


def _services_in(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Services[Any] | None:
    found: list[Services[Any]] = [a for a in (*args, *kwargs.values()) if isinstance(a, Services)]
    if len(found) > 1:
        raise TypeError(
            "a test can use one layer_fixture; merge the layers into one with layer.merge"
        )
    return found[0] if found else None


def _runtime_for(services: Services[Any] | None, options: _Options) -> Runtime:
    if services is None:
        return AsyncioRuntime() if options.asyncio else SyncRuntime()
    if options.asyncio != isinstance(services.runtime, AsyncioRuntime):
        raise TypeError(
            "the test and its layer_fixture must agree on asyncio=; the test runs on "
            "the fixture's runtime"
        )
    return services.runtime


def _context_for(
    services: Services[Any] | None, options: _Options
) -> tuple[Context, TestClock | None]:
    """The test's context, and the ``TestClock`` made for this test alone
    (with a ``TestConsole`` of its own).

    Under a ``layer_fixture`` an ``effect`` test uses the fixture's clock:
    its ``TestClock``, or the live clock of a ``live=True`` fixture."""
    context = Context.empty() if services is None else services.context
    if options.mode == "live":
        return context.add(Clock, LiveClock()), None
    if services is not None:
        return context, None
    clock = TestClock(warning_delay=options.warning_delay)
    return context.add(Clock, clock).add(CurrentConsole, TestConsole()), clock


def _body(
    f: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Effect[Any, Any, Any]:
    def start() -> Effect[Any, Any, Any]:
        out = f(*args, **kwargs)
        if isinstance(out, Effect):
            return out  # pyright: ignore[reportUnknownVariableType]
        if isinstance(out, Generator):
            return _Gen(lambda: out)  # pyright: ignore[reportUnknownLambdaType]
        raise TypeError(
            f"{f.__qualname__} must be a generator (use `yield from`) or return an Effect, "
            f"got {type(out).__name__}"
        )

    return _Suspend(start)
