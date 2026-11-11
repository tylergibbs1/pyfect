"""Strings parsed from configuration and user input: durations, dates and
zones, cron expressions, ``.env`` files, semantic versions and ranges, byte
sizes, decimals, JSON pointers and globs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pyfect import big_decimal, byte_size, cron, duration, glob, json_pointer, semver, semver_range
from pyfect import config as Config
from pyfect import config_provider as cp
from pyfect import date_time as DateTime
from pyfect.config import ConfigError
from pyfect.result import Ok, Result

from ._harness import Crash, raises_only, settle, target, text


@target("duration")
def duration_(data: bytes) -> None:
    """``"<n> <unit>"`` and ISO 8601 durations; a parsed duration's ISO form
    parses to it again."""
    value = text(data)
    for found in (duration.from_input(value), duration.from_iso(value)):
        iso = None if found is None else found.format_iso()
        if found is not None and iso is not None:
            again = duration.from_iso(iso)
            if again != found:
                raise Crash(f"{found!r} -> {iso!r} -> {again!r}")


@target("date_time")
def date_time(data: bytes) -> None:
    value = text(data)
    DateTime.make_zoned_from_string(value)
    DateTime.zone_from_string(value)


@target("cron")
def cron_(data: bytes) -> None:
    """A cron expression (in UTC or a zone the first line names) and its next
    and previous runs."""
    zone, _, expression = text(data).rpartition("\n")
    parsed = raises_only(lambda: cron.parse(expression, zone or None), ValueError)
    if isinstance(parsed, Ok):
        start = datetime(2024, 3, 10, 1, 30, tzinfo=UTC)
        raises_only(lambda: cron.next(parsed.value, start), ValueError)
        raises_only(lambda: cron.prev(parsed.value, start), ValueError)
        cron.format(parsed.value)


@target("dotenv")
def dotenv(data: bytes) -> None:
    """A ``.env`` file (with variable expansion) read as configuration."""
    contents = text(data)
    provider = raises_only(
        lambda: cp.from_dot_env_contents(contents, expand_variables=True), ValueError
    )
    if provider is None:
        return
    config = Config.all(
        Config.option(Config.string("A")),
        Config.option(Config.integer("PORT")),
        Config.option(Config.duration("TIMEOUT")),
        Config.option(Config.boolean("DEBUG")),
    )
    settle(config.parse(provider), ConfigError)


@target("versions")
def versions(data: bytes) -> None:
    """Semantic versions and ranges; a parsed version or range written out
    parses to an equal one."""
    value = text(data)
    _reparses(semver.parse, value)
    _reparses(semver_range.parse, value)


def _reparses[A](parse: Callable[[str], Result[A, object]], value: str) -> None:
    parsed = parse(value)
    if isinstance(parsed, Ok):
        again = parse(str(parsed.value))
        if not (isinstance(again, Ok) and again.value == parsed.value):
            raise Crash(f"{parsed.value!r} written as {str(parsed.value)!r}: {again!r}")


@target("numbers")
def numbers(data: bytes) -> None:
    """Byte sizes and decimals; a parsed decimal written out parses to itself."""
    value = text(data)
    byte_size.from_string(value)
    decimal = big_decimal.from_string(value)
    if decimal is not None:
        again = big_decimal.from_string(decimal.format())
        if again != decimal:
            raise Crash(f"{decimal!r} does not round-trip: {again!r}")


@target("pointer_glob")
def pointer_glob(data: bytes) -> None:
    """A JSON pointer fragment, and a glob matched against the first line."""
    path, _, pattern = text(data).partition("\n")
    json_pointer.parse_uri_fragment(path)
    compiled = raises_only(lambda: glob.make(pattern), ValueError)
    if compiled is not None:
        glob.match(compiled, path)
