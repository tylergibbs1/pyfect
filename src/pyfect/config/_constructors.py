"""The scalar config constructors. Each reads the string at ``name`` (or at
the config's own path when ``name`` is omitted) and is absent when there is
none."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, final, overload, override

from pyfect._one_or_many import one_or_many
from pyfect._url import Url
from pyfect.byte_size import ByteSize
from pyfect.config import _scalars
from pyfect.config._config import Config
from pyfect.config._leaf import scalar_config
from pyfect.config._scalars import LiteralValue
from pyfect.duration import Duration, from_input_unsafe
from pyfect.duration import Input as DurationInput
from pyfect.logger import LogLevel
from pyfect.redacted import Redacted


def string(name: str | None = None) -> Config[str]:
    """Any string."""
    return scalar_config(_scalars.string, name)


def non_empty_string(name: str | None = None) -> Config[str]:
    """A string of at least one character."""
    return scalar_config(_scalars.non_empty_string, name)


def number(name: str | None = None) -> Config[float]:
    """A number, ``"Infinity"``, ``"-Infinity"`` and ``"NaN"`` included
    (Effect's ``Config.Number``)."""
    return scalar_config(_scalars.number, name)


def finite(name: str | None = None) -> Config[float]:
    """A finite number."""
    return scalar_config(_scalars.finite, name)


def integer(name: str | None = None) -> Config[int]:
    """A whole number, read exactly (``"1e3"`` is ``1000``; Effect's
    ``Config.Int``)."""
    return scalar_config(_scalars.integer, name)


def port(name: str | None = None) -> Config[int]:
    """An integer from 1 to 65535."""
    return scalar_config(_scalars.port, name)


def boolean(name: str | None = None) -> Config[bool]:
    """``true`` / ``yes`` / ``on`` / ``1`` / ``y`` or ``false`` / ``no`` /
    ``off`` / ``0`` / ``n``, in lower case."""
    return scalar_config(_scalars.boolean, name)


@overload
def literal[L: LiteralValue](
    values: list[L] | tuple[L, ...], /, *, name: str | None = None
) -> Config[L]: ...
@overload
def literal[L: LiteralValue](*values: L, name: str | None = None) -> Config[L]: ...
def literal(*values: Any, name: str | None = None) -> Config[Any]:
    """One of ``values`` (as arguments or, as in Effect, one list or tuple),
    written as Effect writes literals (``True`` is ``"true"``, ``None`` is
    ``"null"``). Annotate the result to keep the literal types:
    ``env: Config[Literal["dev", "prod"]] = config.literal("dev", "prod")``."""
    return scalar_config(_scalars.literal(one_or_many(values)), name)


def log_level(name: str | None = None) -> Config[LogLevel]:
    """A ``LogLevel`` by Effect's name: ``All``, ``Fatal``, ``Error``,
    ``Warn``, ``Info``, ``Debug``, ``Trace`` or ``None``."""
    return scalar_config(_scalars.log_level, name)


# The runtime types of ``duration.Input``.
_DURATION_INPUTS = (Duration, int, float, str, tuple, dict, timedelta)


@final
class DurationConfig(Config[Duration]):
    """A ``duration`` config, whose ``with_default`` also takes a duration
    input (``"1 second"``), parsed when it is given."""

    __slots__ = ()

    @overload
    def with_default(self, default: DurationInput) -> Config[Duration]: ...
    @overload
    def with_default[B](self, default: B) -> Config[Duration | B]: ...
    @override
    def with_default[B](self, default: DurationInput | B) -> Config[Duration | B]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """``default`` when the value is absent; a duration input is parsed
        now (an invalid one raises ``ValueError``). Invalid data and source
        errors still fail."""
        if isinstance(default, _DURATION_INPUTS):
            return super().with_default(from_input_unsafe(default))  # pyright: ignore[reportArgumentType]
        return super().with_default(default)

    @override
    def nested(self, name: str) -> DurationConfig:
        return DurationConfig(super().nested(name)._evaluate)


def duration(name: str | None = None) -> DurationConfig:
    """A duration such as ``"10 seconds"`` or ``"500 millis"`` (``nanos``
    to ``weeks``, singular or plural), or ``"Infinity"`` / ``"-Infinity"``.
    Its default may be a duration input: ``.with_default("1 second")``."""
    return DurationConfig(scalar_config(_scalars.duration, name)._evaluate)  # pyright: ignore[reportPrivateUsage]


def byte_size(name: str | None = None) -> Config[ByteSize]:
    """An exact size such as ``"10 MB"`` or ``"1.5 KiB"``."""
    return scalar_config(_scalars.byte_size, name)


def date_time(name: str | None = None) -> Config[datetime]:
    """A date as JavaScript's ``Date`` reads it (Effect's ``Config.Date``), as
    a UTC ``datetime``: ISO 8601 (a date alone is UTC, a date-time without
    an offset local time) or V8's other forms (``Jan 15 2024 10:00 PM EST``,
    ``1/15/2024``), local time unless they name a zone."""
    return scalar_config(_scalars.date_time, name)


def url(name: str | None = None) -> Config[Url]:
    """A URL, parsed as ``new URL(text)`` parses it into a ``Url``, whose
    ``str()`` is its ``href`` (``f"{url}/payouts"``)."""
    return scalar_config(_scalars.url, name)


def redacted(name: str | None = None) -> Config[Redacted[str]]:
    """A string hidden in a ``Redacted``."""
    return scalar_config(_scalars.redacted, name)
