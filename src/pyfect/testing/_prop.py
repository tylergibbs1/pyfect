"""Property tests over schemas and Hypothesis strategies (``@effect/vitest``'s
``it.prop``, ``it.effect.prop`` and ``it.live.prop``)::

    @testing.prop(S.Finite, S.Int)
    def test_symmetry(a: float, b: int) -> bool:
        return a + b == b + a

    @testing.effect_prop(text=S.String)
    def test_echo(text: str):
        yield from fx.Console.log(text)

Hypothesis runs the property: a schema is drawn with ``S.to_strategy``, a
strategy as it is. Positional inputs fill the rightmost parameters (as
``@given``'s do), keyword inputs the parameters they name; the others are
pytest fixtures. A property returning ``False`` or raising is falsified and
shrunk. An ``effect_prop`` / ``live_prop`` property is an effect test run
once per drawn input, each run with its own ``TestClock``, ``TestConsole``
and ``Scope``: a typed failure or a defect falsifies it, an interruption or
the ``timeout`` (real time, for the whole check) ends the check without
shrinking. ``runs`` is Hypothesis's ``max_examples`` and ``seed`` its seed;
unset, they come from the active Hypothesis settings profile (Effect's
``Arbitrary.configureGlobal``). Needs the ``pyfect-dev[hypothesis]`` extra.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Callable, Generator, Mapping
from typing import TYPE_CHECKING, Any, cast

from pyfect._core import Effect
from pyfect._extras import missing_extra
from pyfect.duration import Duration, Seconds
from pyfect.exit import Failure, Success
from pyfect.run import unwrap
from pyfect.schema import Codec, to_strategy
from pyfect.scope import scoped
from pyfect.testing._decorators import (
    TestBody,
    _body,
    _context_for,
    _Mode,
    _Options,
    _runtime_for,
    _services_in,
)
from pyfect.testing._decorators import settings as plugin_settings

if TYPE_CHECKING:
    from hypothesis.strategies import SearchStrategy

type Arbitrary = Codec[Any, Any, Any, Any] | SearchStrategy[Any]
"""A property input: a schema (drawn with ``S.to_strategy``) or a Hypothesis
strategy (Effect's ``Arbitrary``)."""

type AnyCodec = Codec[Any, Any, Any, Any]
type Property = Callable[..., bool | None]
type _Decorator = Callable[[Callable[..., Any]], Callable[..., None]]


class PropertyFalsifiedError(AssertionError):
    """A property returned ``False``."""


class _EndCheck(BaseException):
    """Ends the whole check: Hypothesis shrinks on ``Exception``s and lets
    other ``BaseException``s through."""

    def __init__(self, error: BaseException) -> None:
        super().__init__(error)
        self.error = error


def prop(
    *arbitraries: Arbitrary,
    runs: int | None = None,
    seed: int | None = None,
    **keyed: Arbitrary,
) -> Callable[[Property], Callable[..., None]]:
    """A pytest property test: ``f`` returns ``True`` / ``None`` to pass and
    ``False`` to falsify; an effect or generator is refused with
    ``TypeError`` (use ``effect_prop``)."""

    def check(
        f: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any], started: float
    ) -> None:
        out = f(*args, **kwargs)
        if isinstance(out, Effect | Generator) or not (out is None or isinstance(out, bool)):
            raise TypeError(
                "testing.prop properties must return bool or None; "
                "use testing.effect_prop for effects"
            )
        if out is False:
            raise PropertyFalsifiedError(f"property {f.__qualname__} returned False")

    return _property(arbitraries, keyed, runs, seed, check, mode=None)


def effect_prop(
    *arbitraries: Arbitrary,
    runs: int | None = None,
    seed: int | None = None,
    timeout: Duration | None = None,
    asyncio: bool = False,
    warning_delay: Duration = 1.0,
    **keyed: Arbitrary,
) -> Callable[[Callable[..., TestBody[Any]]], Callable[..., None]]:
    """A property test written as an effect (``testing.effect`` per drawn
    input): it fails with ``False``, a typed failure or a defect."""
    options = _Options("effect", timeout, asyncio, warning_delay)
    return _property(arbitraries, keyed, runs, seed, _effect_runner(options), mode="effect")


def live_prop(
    *arbitraries: Arbitrary,
    runs: int | None = None,
    seed: int | None = None,
    timeout: Duration | None = None,
    asyncio: bool = False,
    **keyed: Arbitrary,
) -> Callable[[Callable[..., TestBody[Any]]], Callable[..., None]]:
    """``effect_prop`` with the live clock and console."""
    options = _Options("live", timeout, asyncio, 1.0)
    return _property(arbitraries, keyed, runs, seed, _effect_runner(options), mode="live")


type _Check = Callable[[Callable[..., Any], tuple[Any, ...], dict[str, Any], float], None]
"""Runs the property on one drawn input; ``started`` is when the check
began (``time.monotonic``)."""


def _property(
    arbitraries: tuple[Arbitrary, ...],
    keyed: Mapping[str, Arbitrary],
    runs: int | None,
    seed: int | None,
    check: _Check,
    *,
    mode: _Mode | None,
) -> _Decorator:
    """``mode`` puts the plugin's ``pyfect_effect`` / ``pyfect_live``
    marker on the test."""
    import pytest

    try:
        import hypothesis
        from hypothesis.strategies import SearchStrategy
    except ImportError as error:
        raise missing_extra("testing.prop", "hypothesis") from error

    def decorate(f: Callable[..., Any]) -> Callable[..., None]:
        strategies = _strategies_for(f, arbitraries, keyed, SearchStrategy)
        signature = inspect.signature(f)
        fixtures = [p for name, p in signature.parameters.items() if name not in strategies]

        @functools.wraps(f)
        def run(*args: Any, **kwargs: Any) -> None:
            started = time.monotonic()

            @functools.wraps(f)
            def sample(*args: Any, **kwargs: Any) -> None:
                check(f, args, kwargs, started)

            # Built per run, so unset options follow the profile loaded now.
            options = hypothesis.settings(deadline=None)
            if runs is not None:
                options = hypothesis.settings(options, max_examples=runs)
            test = options(hypothesis.given(**strategies)(sample))
            if seed is not None:
                test = hypothesis.seed(seed)(test)
            try:
                test(*args, **kwargs)
            except _EndCheck as end:
                raise end.error from None

        run.__signature__ = signature.replace(parameters=fixtures)  # pyright: ignore[reportAttributeAccessIssue]
        match mode:
            case "effect":
                return pytest.mark.pyfect_effect(run)
            case "live":
                return pytest.mark.pyfect_live(run)
            case None:
                return run

    return decorate


def _strategies_for(
    f: Callable[..., Any],
    arbitraries: tuple[Arbitrary, ...],
    keyed: Mapping[str, Arbitrary],
    strategy_type: type[SearchStrategy[Any]],
) -> dict[str, SearchStrategy[Any]]:
    params = list(inspect.signature(f).parameters)
    unknown = keyed.keys() - set(params)
    if unknown:
        raise TypeError(f"{f.__qualname__} has no parameter(s) {sorted(unknown)}")
    free = [name for name in params if name not in keyed]
    if len(arbitraries) > len(free):
        raise TypeError(
            f"{f.__qualname__} has {len(free)} parameter(s) left, "
            f"too few for {len(arbitraries)} positional property inputs"
        )
    named = dict(zip(free[len(free) - len(arbitraries) :], arbitraries, strict=True))
    return {
        name: input if isinstance(input, strategy_type) else to_strategy(cast("AnyCodec", input))
        for name, input in {**named, **keyed}.items()
    }


def _effect_runner(options: _Options) -> _Check:
    """One effect test per drawn input; the timeout is for the whole check."""

    def check(
        f: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any], started: float
    ) -> None:
        limit = options.timeout if options.timeout is not None else plugin_settings.timeout
        left = None if limit is None else Seconds(max(limit - (time.monotonic() - started), 0.0))
        _run_sample(f, args, kwargs, options, left)

    return check


def _run_sample(
    f: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    options: _Options,
    timeout: Seconds | None,
) -> None:
    services = _services_in(args, kwargs)
    runtime = _runtime_for(services, options)
    context, clock = _context_for(services, options)
    try:
        ex = runtime.run(scoped(_body(f, args, kwargs)), context, timeout=timeout)
    except TimeoutError as error:
        raise _EndCheck(error) from None
    finally:
        if clock is not None:
            clock.stop_warning()
        if services is None:
            runtime.close()
    match ex:
        case Failure(cause=cause) if cause.has_interrupts:
            raise _EndCheck(cause.squash())
        case Success(value=False):
            raise PropertyFalsifiedError(f"property {f.__qualname__} returned False")
        case _:
            unwrap(ex)


__all__ = ["Arbitrary", "PropertyFalsifiedError", "effect_prop", "live_prop", "prop"]
