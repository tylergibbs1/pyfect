"""(pyfect) Every parser and decoder of peer input takes time near linear in its input.

The cases live in ``_parser_cases``. ``test_every_parser_is_measured`` walks pyfect's public
modules for parser-like functions (``parse``, ``decode``, ``from_string`` and the like) and
schemas decoding text (``*FromString``), and fails on one that no case measures and
``NOT_MEASURED`` does not explain, so a new parser cannot ship without a case.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from _growth import GUARD_MARGIN, assert_near_linear, cpu_pair
from _guards import Guard
from _pyfect_modules import modules

from pyfect import schema as S

from ._parser_cases import AMPLIFIED, CASES, NOT_MEASURED, Amplified, Case

_PARSER_NAME = re.compile(
    r"^(parse|decode|unsafe_parse|from_string|from_text|from_json|read)"
    r"|(_from_string|_from_text|_parse|_decode)$"
)


def _marks(fixed_elsewhere: str | None, guards: Guard | None) -> list[Any]:
    marks: list[Any] = [] if guards is None else [guards.mark]
    if fixed_elsewhere is not None:
        marks.append(pytest.mark.xfail(reason=fixed_elsewhere, strict=True))
    return marks


def _cases() -> Iterator[Any]:
    for found in CASES:
        yield pytest.param(found, id=found.id, marks=_marks(found.fixed_elsewhere, found.guards))


@pytest.mark.parametrize("found", list(_cases()))
def test_parser_takes_near_linear_time(found: Case) -> None:
    assert_near_linear(found.make, found.size, found.max_size, factor=found.factor)


@pytest.mark.parametrize(
    "found", [pytest.param(a, id=a.id, marks=_marks(None, a.guards)) for a in AMPLIFIED]
)
def test_costly_input_costs_about_as_much_as_plain_input(found: Amplified) -> None:
    costly, plain = cpu_pair(found.costly, found.plain)
    assert costly <= found.bound * GUARD_MARGIN * max(plain, 0.001), (
        f"{costly * 1000:.1f} ms against {plain * 1000:.1f} ms for plain input"
    )


def _public_values() -> Iterator[tuple[str, object]]:
    for module in modules(public=True, skip_missing_extras=True):
        for name in getattr(module, "__all__", ()):
            yield name, getattr(module, name, None)


def canonical(target: object) -> str:
    """A function by where it is defined, a schema by its public name."""
    if S.is_schema(target):
        return next((f"schema {n}" for n, v in _public_values() if v is target), repr(target))
    return f"{getattr(target, '__module__', '')}.{getattr(target, '__qualname__', '')}"


def public_parsers() -> set[str]:
    found: set[str] = set()
    for name, value in _public_values():
        if name.endswith("FromString") and S.is_schema(value):
            found.add(f"schema {name}")
        elif _PARSER_NAME.search(name) and callable(value) and not isinstance(value, type):
            found.add(canonical(value))
    return found


def test_every_parser_is_measured() -> None:
    measured = {canonical(found.target) for found in CASES} | {
        canonical(found.target) for found in AMPLIFIED
    }
    parsers = public_parsers()
    missing = sorted(parsers - measured - NOT_MEASURED.keys())
    assert not missing, (
        f"parsers with no case in _parser_cases and no NOT_MEASURED reason: {missing}"
    )
    stale = sorted(NOT_MEASURED.keys() - parsers)
    assert not stale, f"NOT_MEASURED names no public parser: {stale}"
    explained = sorted(NOT_MEASURED.keys() & measured)
    assert not explained, f"NOT_MEASURED names a measured parser: {explained}"
