"""Length, size and collection checks (Effect's ``isMinLength``,
``isMaxSize``, ``isMinProperties``, ``isUnique``, ``isPropertyNames``, ...).

Python measures every one with ``len``: a string's length counts code
points (JavaScript counts UTF-16 units), so the ``code_points`` checks
agree with the ``length`` ones on strings. ``size`` (Effect's ``Set`` /
``Map``) and ``properties`` (an object's keys) are ``len`` of a set or a
mapping. A negative bound counts as ``0``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence, Sized
from typing import Any

from pyfect.exit import Success
from pyfect.schema._options import ParseOptions
from pyfect.schema._schema import Top
from pyfect.schema.ast import AST, Filter, filter_of, issue_of, run_now
from pyfect.schema.issue import Composite, Issue, Pointer, reported


def _sized(
    accepts: Callable[[int], bool],
    expected: str,
    id: str,
    payload: object,
    annotations: dict[str, object],
) -> Filter[Sized]:
    return filter_of(
        lambda value: accepts(len(value)),
        {
            "expected": expected,
            "representation": {"id": f"effect/schema/{id}", "payload": payload},
            **annotations,
        },
    )


def _between(minimum: int, maximum: int, exactly: str, between: str) -> str:
    return exactly if minimum == maximum else between


def is_min_length(min_length: int, /, **annotations: object) -> Filter[Sized]:
    n = max(0, min_length)
    return _sized(
        lambda length: length >= n,
        f"a value with a length of at least {n}",
        "isMinLength",
        {"minLength": n},
        annotations,
    )


def is_non_empty(**annotations: object) -> Filter[Sized]:
    """``is_min_length(1)``."""
    return is_min_length(1, **annotations)


def is_max_length(max_length: int, /, **annotations: object) -> Filter[Sized]:
    n = max(0, max_length)
    return _sized(
        lambda length: length <= n,
        f"a value with a length of at most {n}",
        "isMaxLength",
        {"maxLength": n},
        annotations,
    )


def is_between_length(minimum: int, maximum: int, /, **annotations: object) -> Filter[Sized]:
    low, high = max(0, minimum), max(0, maximum)
    return _sized(
        lambda length: low <= length <= high,
        _between(
            low,
            high,
            f"a value with a length of {low}",
            f"a value with a length between {low} and {high}",
        ),
        "isBetweenLength",
        {"minimum": low, "maximum": high},
        annotations,
    )


def is_min_code_points(min_code_points: int, /, **annotations: object) -> Filter[str]:
    n = max(0, min_code_points)
    return _sized(
        lambda count: count >= n,
        f"a string with at least {n} code points",
        "isMinCodePoints",
        {"minCodePoints": n},
        annotations,
    )


def is_max_code_points(max_code_points: int, /, **annotations: object) -> Filter[str]:
    n = max(0, max_code_points)
    return _sized(
        lambda count: count <= n,
        f"a string with at most {n} code points",
        "isMaxCodePoints",
        {"maxCodePoints": n},
        annotations,
    )


def is_between_code_points(minimum: int, maximum: int, /, **annotations: object) -> Filter[str]:
    low, high = max(0, minimum), max(0, maximum)
    return _sized(
        lambda count: low <= count <= high,
        _between(
            low,
            high,
            f"a string with {low} code points",
            f"a string with between {low} and {high} code points",
        ),
        "isBetweenCodePoints",
        {"minimum": low, "maximum": high},
        annotations,
    )


def is_min_size(min_size: int, /, **annotations: object) -> Filter[Sized]:
    n = max(0, min_size)
    return _sized(
        lambda size: size >= n,
        f"a value with a size of at least {n}",
        "isMinSize",
        {"minSize": n},
        annotations,
    )


def is_max_size(max_size: int, /, **annotations: object) -> Filter[Sized]:
    n = max(0, max_size)
    return _sized(
        lambda size: size <= n,
        f"a value with a size of at most {n}",
        "isMaxSize",
        {"maxSize": n},
        annotations,
    )


def is_between_size(minimum: int, maximum: int, /, **annotations: object) -> Filter[Sized]:
    low, high = max(0, minimum), max(0, maximum)
    return _sized(
        lambda size: low <= size <= high,
        _between(
            low,
            high,
            f"a value with a size of {low}",
            f"a value with a size between {low} and {high}",
        ),
        "isBetweenSize",
        {"minimum": low, "maximum": high},
        annotations,
    )


def _entries(n: int) -> str:
    return "1 entry" if n == 1 else f"{n} entries"


def is_min_properties(min_properties: int, /, **annotations: object) -> Filter[Sized]:
    n = max(0, min_properties)
    return _sized(
        lambda count: count >= n,
        f"a value with at least {_entries(n)}",
        "isMinProperties",
        {"minProperties": n},
        annotations,
    )


def is_max_properties(max_properties: int, /, **annotations: object) -> Filter[Sized]:
    n = max(0, max_properties)
    return _sized(
        lambda count: count <= n,
        f"a value with at most {_entries(n)}",
        "isMaxProperties",
        {"maxProperties": n},
        annotations,
    )


def is_between_properties(minimum: int, maximum: int, /, **annotations: object) -> Filter[Sized]:
    low, high = max(0, minimum), max(0, maximum)
    return _sized(
        lambda count: low <= count <= high,
        _between(
            low,
            high,
            f"a value with exactly {_entries(low)}",
            f"a value with between {low} and {high} entries",
        ),
        "isBetweenProperties",
        {"minimum": low, "maximum": high},
        annotations,
    )


def is_property_names(key_schema: Top, /, **annotations: object) -> Filter[Mapping[Any, object]]:
    """A mapping whose every key is a value of ``key_schema``'s encoded
    side; each bad key's issue is reported at that key."""
    keys = key_schema.__codec__().ast.flip().to_type()

    def run(input: Mapping[Any, object], ast: AST, options: ParseOptions) -> Issue | None:
        issues: list[Issue] = []
        for key in input:
            match run_now(keys.parse(key, options)):
                case Success():
                    pass
                case failure:
                    issue = issue_of(failure)
                    if issue is None:
                        raise failure.cause.squash()
                    issues.append(Pointer((key,), issue))
                    if options.get("errors") != "all":
                        break
        if not issues:
            return None
        return Composite(ast, (issues[0], *issues[1:]), reported(input, options))

    return Filter(
        run,
        {
            "expected": "an object with property names matching the schema",
            "representation": {"id": "effect/schema/isPropertyNames", "payload": None},
            **annotations,
        },
    )


def _all_unique(items: Sequence[object]) -> bool:
    try:
        return len(set(items)) == len(items)
    except TypeError:
        seen: list[object] = []
        for item in items:
            if item in seen:
                return False
            seen.append(item)
        return True


def is_unique(**annotations: object) -> Filter[Sequence[object]]:
    """A sequence with no two equal (``==``) items."""
    return filter_of(
        _all_unique,
        {
            "expected": "an array with unique items",
            "representation": {"id": "effect/schema/isUnique", "payload": None},
            **annotations,
        },
    )


def is_unique_key(**annotations: object) -> Filter[Sequence[tuple[object, object]]]:
    """A sequence of pairs with no two equal keys."""
    return filter_of(
        lambda pairs: _all_unique([key for key, _ in pairs]),
        {
            "expected": "an array with unique keys",
            "representation": {"id": "effect/schema/isUniqueKey", "payload": None},
            **annotations,
        },
    )
