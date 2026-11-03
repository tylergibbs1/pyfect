"""The scalar config constructors. Each reads the string at ``name`` (or at
the config's own path when ``name`` is omitted) and is absent when there is
none."""

from __future__ import annotations

from datetime import datetime
from typing import Any, overload

from pyfect._one_or_many import one_or_many
from pyfect._url import Url
from pyfect.byte_size import ByteSize
from pyfect.config import _scalars
from pyfect.config._config import Config
from pyfect.config._leaf import scalar_config
from pyfect.config._scalars import LiteralValue
from pyfect.duration import Seconds
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


def duration(name: str | None = None) -> Config[Seconds]:
    """A duration such as ``"10 seconds"`` or ``"500 millis"`` (``nanos``
    to ``weeks``, singular or plural), or ``"Infinity"`` / ``"-Infinity"``."""
    return scalar_config(_scalars.duration, name)


def byte_size(name: str | None = None) -> Config[ByteSize]:
    """An exact size such as ``"10 MB"`` or ``"1.5 KiB"``."""
    return scalar_config(_scalars.byte_size, name)


def date_time(name: str | None = None) -> Config[datetime]:
    """An ISO 8601 date or date-time (read as JavaScript's ``Date`` reads it); one with
    no offset is UTC (Effect's ``Config.Date``)."""
    return scalar_config(_scalars.date_time, name)


def url(name: str | None = None) -> Config[Url]:
    """An absolute URL with a scheme (and a host for ``http``, ``https``,
    ``ws``, ``wss`` and ``ftp``), split by ``urllib.parse.urlsplit`` into a
    ``Url``, whose ``str()`` is the URL (``f"{url}/payouts"``)."""
    return scalar_config(_scalars.url, name)


def redacted(name: str | None = None) -> Config[Redacted[str]]:
    """A string hidden in a ``Redacted``."""
    return scalar_config(_scalars.redacted, name)
