"""The ``to_equivalence`` and ``to_formatter`` annotations of the built-in
declarations: Effect's ``toEquivalence`` / ``toFormatter`` cases for
``Option``, ``Result``, ``CauseReason``, ``Cause``, ``Exit``, sets, maps,
``Redacted``, ``URL``, date-times and zones."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import tzinfo
from typing import Any, cast

from pyfect import redacted
from pyfect._js import js_sort_key
from pyfect._url import Url
from pyfect.cause import Cause, Die, Fail, Interrupt, Reason
from pyfect.date_time import format_iso_zoned, zone_to_string
from pyfect.date_time._iso import utc_to_string
from pyfect.exit import Exit, Success
from pyfect.option import Option, Some
from pyfect.result import Ok, Result
from pyfect.schema._to_equivalence import Equivalence, same_items
from pyfect.schema._to_formatter import Formatter

type _Equivalences = tuple[Equivalence[Any], ...]
type _Formatters = tuple[Formatter[Any], ...]


def _fixed[A](instance: A) -> Callable[[tuple[object, ...]], A]:
    return lambda _: instance


# ------------------------------------------------------------------ Option


def option_equivalence(parameters: _Equivalences) -> Equivalence[Option[object]]:
    (value,) = parameters

    def equivalent(a: Option[object], b: Option[object]) -> bool:
        if isinstance(a, Some) and isinstance(b, Some):
            return value(a.value, b.value)
        return a is None and b is None

    return equivalent


def option_formatter(parameters: _Formatters) -> Formatter[Option[object]]:
    (value,) = parameters
    return lambda o: f"some({value(o.value)})" if isinstance(o, Some) else "none()"


# ------------------------------------------------------------------ Result


def result_equivalence(parameters: _Equivalences) -> Equivalence[Result[object, object]]:
    success, failure = parameters

    def equivalent(a: Result[object, object], b: Result[object, object]) -> bool:
        match a, b:
            case Ok(), Ok():
                return success(a.value, b.value)
            case Ok(), _:
                return False
            case _, Ok():
                return False
            case _:
                return failure(a.error, b.error)

    return equivalent


def result_formatter(parameters: _Formatters) -> Formatter[Result[object, object]]:
    success, failure = parameters
    return lambda r: (
        f"success({success(r.value)})" if isinstance(r, Ok) else f"failure({failure(r.error)})"
    )


# ------------------------------------------------------------------- Cause


def _reason_equivalence(
    error: Equivalence[object], defect: Equivalence[object]
) -> Equivalence[Reason[object]]:
    def equivalent(a: Reason[object], b: Reason[object]) -> bool:
        if type(a) is not type(b):
            return False
        match a:
            case Fail():
                return error(a.error, cast("Fail[object]", b).error)
            case Die():
                return defect(a.defect, cast("Die", b).defect)
            case _:
                return a.fiber_id == cast("Interrupt", b).fiber_id

    return equivalent


def _reason_formatter(
    error: Formatter[object], defect: Formatter[object]
) -> Formatter[Reason[object]]:
    def format(reason: Reason[object]) -> str:
        match reason:
            case Fail():
                return f"Fail({error(reason.error)})"
            case Die():
                return f"Die({defect(reason.defect)})"
            case _:
                return "Interrupt"

    return format


def _cause_equivalence(
    error: Equivalence[object], defect: Equivalence[object]
) -> Equivalence[Cause[object]]:
    reason = _reason_equivalence(error, defect)

    def equivalent(a: Cause[object], b: Cause[object]) -> bool:
        return len(a.reasons) == len(b.reasons) and all(map(reason, a.reasons, b.reasons))

    return equivalent


def _cause_formatter(
    error: Formatter[object], defect: Formatter[object]
) -> Formatter[Cause[object]]:
    reason = _reason_formatter(error, defect)
    return lambda cause: f"Cause([{', '.join(map(reason, cause.reasons))}])"


def reason_equivalence(parameters: _Equivalences) -> Equivalence[Reason[object]]:
    return _reason_equivalence(*parameters)


def reason_formatter(parameters: _Formatters) -> Formatter[Reason[object]]:
    return _reason_formatter(*parameters)


def cause_equivalence(parameters: _Equivalences) -> Equivalence[Cause[object]]:
    return _cause_equivalence(*parameters)


def cause_formatter(parameters: _Formatters) -> Formatter[Cause[object]]:
    return _cause_formatter(*parameters)


def exit_equivalence(parameters: _Equivalences) -> Equivalence[Exit[object, object]]:
    value, error, defect = parameters
    cause = _cause_equivalence(error, defect)

    def equivalent(a: Exit[object, object], b: Exit[object, object]) -> bool:
        match a, b:
            case Success(), Success():
                return value(a.value, b.value)
            case Success(), _:
                return False
            case _, Success():
                return False
            case _:
                return cause(a.cause, b.cause)

    return equivalent


def exit_formatter(parameters: _Formatters) -> Formatter[Exit[object, object]]:
    value, error, defect = parameters
    cause = _cause_formatter(error, defect)
    return lambda e: (
        f"Exit.Success({value(e.value)})"
        if isinstance(e, Success)
        else f"Exit.Failure({cause(e.cause)})"
    )


# ------------------------------------------------------- Sets and maps


def set_equivalence(parameters: _Equivalences) -> Equivalence[Iterable[object]]:
    return same_items(parameters[0])


def set_formatter(parameters: _Formatters) -> Formatter[frozenset[object]]:
    (value,) = parameters

    def format(items: frozenset[object]) -> str:
        if not items:
            return "FrozenSet(0) {}"
        texts = sorted(map(value, items), key=js_sort_key)
        return f"FrozenSet({len(items)}) {{ {', '.join(texts)} }}"

    return format


def map_equivalence(parameters: _Equivalences) -> Equivalence[Mapping[object, object]]:
    key, value = parameters

    def same_entry(a: tuple[object, object], b: tuple[object, object]) -> bool:
        return key(a[0], b[0]) and value(a[1], b[1])

    entries = same_items(same_entry)
    return lambda a, b: entries(a.items(), b.items())


def map_formatter(parameters: _Formatters) -> Formatter[Mapping[object, object]]:
    key, value = parameters

    def format(entries: Mapping[object, object]) -> str:
        if not entries:
            return "Map(0) {}"
        texts = sorted((f"{key(k)} => {value(v)}" for k, v in entries.items()), key=js_sort_key)
        return f"Map({len(entries)}) {{ {', '.join(texts)} }}"

    return format


# ---------------------------------------------------------------- Values


def redacted_equivalence(parameters: _Equivalences) -> Equivalence[redacted.Redacted[object]]:
    (value,) = parameters
    return lambda a, b: value(redacted.value(a), redacted.value(b))


def _url_text(url: Url) -> str:
    return url.href


def _same_url(a: Url, b: Url) -> bool:
    return a.href == b.href


URL_INSTANCES: dict[str, object] = {
    "to_equivalence": _fixed(_same_url),
    "to_formatter": _fixed(_url_text),
}


DATE_TIME_UTC_FORMATTER = _fixed(utc_to_string)
DATE_TIME_ZONED_FORMATTER = _fixed(format_iso_zoned)
ZONE_FORMATTER: Callable[[tuple[object, ...]], Formatter[tzinfo]] = _fixed(zone_to_string)
