"""``Config[A]``: how to read and decode one value from a ``ConfigProvider``.

A config resolves in two channels. Data that is simply not there is
*absent*: an ``Err`` inside a successful evaluation, which ``with_default``
and ``option`` recover. Data that is there but invalid, and a source that
cannot be read, are *failures* of the evaluation, which only ``or_else``
recovers. ``parse`` turns absence into a failure too, so a config run on its
own fails with ``ConfigError`` either way.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from typing import TYPE_CHECKING, Any, Never, overload, override

from pyfect._core import Effect, _Suspend
from pyfect._effect_base import A_co
from pyfect.cause import Cause, Fail
from pyfect.config._error import ConfigError
from pyfect.config_provider import ConfigProvider, CurrentConfigProvider, Path, SourceError
from pyfect.effect import fail_cause, succeed, sync
from pyfect.option import Option, Some
from pyfect.result import Err, Ok, Result
from pyfect.schema import SchemaError

if TYPE_CHECKING:
    from pyfect._fiber import Fiber

type Resolution[A] = Result[A, ConfigError]
"""``Ok`` when the value was found, ``Err`` when it is absent."""

type Evaluate[A] = Callable[[ConfigProvider, Path], Effect[Resolution[A], ConfigError]]
"""Evaluate a config with a provider under a path prefix (from ``nested``)."""


class Config(Effect[A_co, ConfigError]):
    """A recipe for reading a typed value from a ``ConfigProvider``.

    A config is an effect: running it (``yield from port`` inside
    ``fx.gen``) reads the ``CurrentConfigProvider``. ``parse(provider)``
    reads a given one. The methods build new configs (an ``Effect`` method
    that ``Effect``'s ``Config`` module also defines, such as ``option``,
    has the ``Config`` meaning); the constructors are in ``pyfect.config``."""

    __slots__ = ("_evaluate",)

    def __init__(self, evaluate: Evaluate[A_co]) -> None:
        self._evaluate = evaluate

    @override
    def _step(self, fiber: Fiber[Any, Any]) -> Effect[A_co, ConfigError]:
        return self.parse(fiber.get_ref(CurrentConfigProvider))

    def parse(self, provider: ConfigProvider) -> Effect[A_co, ConfigError]:
        """Read this config from ``provider``; absence fails too."""
        return self._evaluate(provider, ()).flat_map(_present_or_fail)

    @override
    def map[B](self, f: Callable[[A_co], B]) -> Config[B]:
        evaluate = self._evaluate
        return Config(lambda provider, prefix: evaluate(provider, prefix).map(lambda r: r.map(f)))

    @overload
    def flat_map[B](self, f: Callable[[A_co], Config[B]]) -> Config[B]: ...
    @overload
    def flat_map[B, E2 = Never, R2 = Never](
        self, f: Callable[[A_co], Effect[B, E2, R2]]
    ) -> Effect[B, ConfigError | E2, R2]: ...
    @override
    def flat_map(self, f: Callable[[A_co], Effect[Any, Any, Any]]) -> Effect[Any, Any, Any]:
        """Choose the next config from this one's value; it is read under
        the same ``nested`` prefix. Absence of either is absence. A function
        returning a plain effect gives a plain effect, as ``Effect.flat_map``
        does."""
        evaluate = self._evaluate

        def run(provider: ConfigProvider, prefix: Path) -> Effect[Resolution[Any], Any]:
            def next_config(resolution: Resolution[A_co]) -> Effect[Resolution[Any], Any]:
                match resolution:
                    case Ok(value):
                        return _evaluate_at(f(value), provider, prefix)
                    case Err():
                        return succeed(resolution)

            return evaluate(provider, prefix).flat_map(next_config)

        return Config(run)

    def map_effect[B](self, f: Callable[[A_co], Effect[B, ConfigError]]) -> Config[B]:
        """Transform the value with an effect that may fail (Effect's
        ``mapEffect``); its failure is a failure, not absence."""
        evaluate = self._evaluate

        def next_value(resolution: Resolution[A_co]) -> Effect[Resolution[B], ConfigError]:
            match resolution:
                case Ok(value):
                    return f(value).map(Ok)
                case Err():
                    return succeed(resolution)

        return Config(lambda provider, prefix: evaluate(provider, prefix).flat_map(next_value))

    def or_else[B](self, that: Callable[[ConfigError], Config[B]]) -> Config[A_co | B]:
        """Read ``that(error)`` when this config is absent or fails with a
        ``ConfigError``. Defects and interruptions are not recovered, nor is
        a failure that comes with one."""
        evaluate = self._evaluate

        def run(
            provider: ConfigProvider, prefix: Path
        ) -> Effect[Resolution[A_co | B], ConfigError]:
            def on_failure(cause: Cause[ConfigError]) -> Effect[Resolution[B], ConfigError]:
                match cause.reasons:
                    case (Fail(error), *rest) if all(isinstance(r, Fail) for r in rest):
                        return that(error)._evaluate(provider, prefix)
                    case _:
                        return fail_cause(cause)

            def on_success(
                resolution: Resolution[A_co],
            ) -> Effect[Resolution[A_co | B], ConfigError]:
                match resolution:
                    case Ok():
                        return succeed(resolution)
                    case Err(error):
                        return that(error)._evaluate(provider, prefix)

            return evaluate(provider, prefix).match_cause_effect(
                on_failure=on_failure, on_success=on_success
            )

        return Config(run)

    @overload
    def with_default[B](self: Config[B], default: B) -> Config[B]: ...
    @overload
    def with_default[B](  # pyright: ignore[reportOverlappingOverload]
        self, default: B
    ) -> Config[A_co | B]: ...
    def with_default[B](self, default: B) -> Config[A_co | B]:
        """``default`` when the value is absent. Invalid data and source
        errors still fail. A group from ``all`` is absent as a whole when
        any part is."""
        evaluate = self._evaluate
        present: Resolution[B] = Ok(default)

        def recover(resolution: Resolution[A_co]) -> Resolution[A_co | B]:
            return present if isinstance(resolution, Err) else resolution

        return Config(lambda provider, prefix: evaluate(provider, prefix).map(recover))

    @override
    def option(self) -> Config[Option[A_co]]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """``Some(value)``, or ``None`` when the value is absent (Effect's
        ``Config.option``). Invalid data and source errors still fail: this
        is not ``Effect.option``, which would turn them into ``None``."""
        return self.map(Some).with_default(None)

    def nested(self, name: str) -> Config[A_co]:
        """Read this config under ``name``: an object level in
        ``from_unknown``, a ``name_`` prefix in ``from_env``. The outermost
        ``nested`` is the outermost segment."""
        evaluate = self._evaluate
        return Config(lambda provider, prefix: evaluate(provider, (*prefix, name)))

    @override
    def __repr__(self) -> str:
        return "Config()"


def _present_or_fail[A](resolution: Resolution[A]) -> Effect[A, ConfigError]:
    match resolution:
        case Ok(value):
            return succeed(value)
        case Err(error):
            return fail_cause(Cause((Fail(error),)))


def _evaluate_at(
    eff: Effect[Any, Any, Any], provider: ConfigProvider, prefix: Path
) -> Effect[Resolution[Any], Any]:
    """A config read under ``prefix``; any other effect run for its value."""
    if isinstance(eff, Config):
        return eff._evaluate(provider, prefix)
    return eff.map(Ok)


def require_config(value: object, name: str) -> None:
    if not isinstance(value, Config):
        raise TypeError(f"{name} must be a Config, got {type(value).__name__}: {value!r}")


def succeed_config[A](value: A) -> Config[A]:
    """A config that reads nothing and gives ``value``."""
    present: Resolution[A] = Ok(value)
    return Config(lambda _provider, _prefix: succeed(present))


def fail_config(error: SourceError | SchemaError) -> Config[Never]:
    """A config that always fails with ``ConfigError(error)``."""
    failure: Effect[Never, ConfigError] = fail_cause(Cause((Fail(ConfigError(error)),)))
    return Config(lambda _provider, _prefix: failure)


def option[A](config: Config[A]) -> Config[Option[A]]:
    """``config.option()``: ``Some(value)``, or ``None`` when the value is
    absent. Invalid data and source errors still fail."""
    return config.option()


def gen[A](f: Callable[[], Generator[Effect[Any, ConfigError, Never], Any, A]]) -> Config[A]:
    """Build a config from a generator: ``x = yield from cfg`` reads
    ``cfg`` under the result's ``nested`` prefix, and the result is absent
    as soon as one read is. Other effects run as they are (they may fail
    only with ``ConfigError`` and need no services)::

        @config.gen
        def server():
            host = yield from config.string("HOST")
            port = yield from config.port("PORT").with_default(8080)
            return f"{host}:{port}"
    """

    def run(provider: ConfigProvider, prefix: Path) -> Effect[Resolution[A], ConfigError]:
        def start() -> Effect[Resolution[A], ConfigError]:
            generator = f()

            def advance(send: Callable[[], Effect[Any, ConfigError, Never]]) -> Effect[Any, Any]:
                try:
                    yielded = send()
                except StopIteration as stop:
                    done: Resolution[A] = Ok(stop.value)
                    return succeed(done)

                def next_step(resolution: Resolution[Any]) -> Effect[Any, Any]:
                    match resolution:
                        case Ok(value):
                            return advance(lambda: generator.send(value))
                        case Err():
                            return succeed(resolution)

                return _evaluate_at(yielded, provider, prefix).flat_map(next_step)

            # Closing runs the generator's ``finally`` blocks however the
            # read ends: absent, failed, interrupted or done (a no-op then).
            return advance(lambda: next(generator)).ensuring(sync(generator.close))

        return _Suspend(start)

    return Config(run)


def unwrap(wrapped: Config[Any] | Mapping[str, Any]) -> Config[Any]:
    """A config itself, or a (nested) mapping of configs read as one
    ``all_dict`` per level."""
    from pyfect.config._all import all_dict

    if isinstance(wrapped, Config):
        return wrapped
    return all_dict({key: unwrap(value) for key, value in wrapped.items()})
