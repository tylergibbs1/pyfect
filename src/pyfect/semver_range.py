"""npm-style version ranges (Effect's ``SemVerRange``)::

    r = semver_range.parse_unsafe("^1.2.3 || >=3")
    r.matches("1.9.0")                       # True
    r.max_satisfying(["1.2.0", "1.4.1", "2.0.0"])  # SemVer 1.4.1

The grammar is node-semver's: ``^`` / ``~``, comparators (``<``, ``<=``,
``>``, ``>=``, ``=``), x-ranges (``1.x``, ``1.2.*``, ``*``), hyphen ranges
(``1.2.3 - 2``) and ``||`` alternatives; build metadata is rejected. A
pre-release matches only through a bound with a pre-release on the same
MAJOR.MINOR.PATCH, unless ``include_prerelease``. Two ranges are equal
when they format the same.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Literal

from pyfect._json_text import quote
from pyfect.result import Ok, Result
from pyfect.semver import (
    Identifier,
    SemVer,
    SemVerError,
    compare_core,
    invalid,
    parse_component,
    prerelease_identifier,
    same_core,
    try_parse,
)
from pyfect.semver import Input as VersionInput
from pyfect.semver import from_input_unsafe as version_from_input_unsafe

type Operator = Literal["=", "<", "<=", ">", ">=", "~", "^"]
type _BoundOperator = Literal["=", "<", "<=", ">", ">="]


@dataclass(frozen=True)
class _Partial:
    components: tuple[int, ...]
    """The components before the first wildcard; empty for ``*``."""
    prerelease: tuple[Identifier, ...] = ()
    """Only a full MAJOR.MINOR.PATCH carries one."""


@dataclass(frozen=True)
class _Comparator:
    operator: Operator
    version: _Partial


@dataclass(frozen=True)
class _Hyphen:
    start: _Partial
    end: _Partial


type _Clause = _Comparator | _Hyphen


@dataclass(frozen=True)
class _Bound:
    operator: _BoundOperator
    major: int
    minor: int
    patch: int
    prerelease: tuple[Identifier, ...]


class SemVerRange:
    """A parsed range; build one with ``parse`` or the constructors."""

    def __init__(self, sets: tuple[tuple[_Clause, ...], ...]) -> None:
        self._sets = sets

    def format(self) -> str:
        """The normalized text: ``1.x`` is ``1``, ``>= 1.2.3`` is ``>=1.2.3``."""
        return " || ".join(" ".join(map(_format_clause, s)) for s in self._sets)

    def __str__(self) -> str:
        return self.format()

    def __repr__(self) -> str:
        return f"SemVerRange({self.format()})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVerRange):
            return NotImplemented
        return self.format() == other.format()

    def __hash__(self) -> int:
        return hash(self.format())

    @cached_property
    def _release_bounds(self) -> tuple[tuple[_Bound, ...], ...]:
        return _compile(self._sets, include_prerelease=False)

    @cached_property
    def _prerelease_bounds(self) -> tuple[tuple[_Bound, ...], ...]:
        return _compile(self._sets, include_prerelease=True)

    def _test(self, version: SemVer, include_prerelease: bool) -> bool:
        sets = self._prerelease_bounds if include_prerelease else self._release_bounds
        return any(
            all(_test_bound(b, version) for b in bounds)
            and (
                include_prerelease
                or not version.prerelease
                or any(b.prerelease and same_core(b, version) for b in bounds)
            )
            for bounds in sets
        )

    def matches(self, version: VersionInput, *, include_prerelease: bool = False) -> bool:
        """Whether ``version`` is in the range; raises ``SemVerError`` for
        an invalid version."""
        return self._test(version_from_input_unsafe(version), include_prerelease)

    def _select(
        self, versions: Iterable[VersionInput], include_prerelease: bool, better: int
    ) -> SemVer | None:
        selected: SemVer | None = None
        for value in versions:
            version = version_from_input_unsafe(value)
            if self._test(version, include_prerelease) and (
                selected is None or compare_core(version, selected) == better
            ):
                selected = version
        return selected

    def max_satisfying(
        self, versions: Iterable[VersionInput], *, include_prerelease: bool = False
    ) -> SemVer | None:
        """The highest version in the range (the first of equal ones)."""
        return self._select(versions, include_prerelease, 1)

    def min_satisfying(
        self, versions: Iterable[VersionInput], *, include_prerelease: bool = False
    ) -> SemVer | None:
        """The lowest version in the range (the first of equal ones)."""
        return self._select(versions, include_prerelease, -1)


# --- parsing --------------------------------------------------------------------------

_WILDCARD = _Partial(())
_OPERATORS: tuple[Operator, ...] = ("<=", ">=", "<", ">", "=", "~", "^")
_LABELS = ("major", "minor", "patch")


def _parse_partial(text: str) -> _Partial:
    if not text:
        invalid("expected a version after the operator")
    if "+" in text:
        invalid(f"build metadata is not allowed in ranges, received {quote(text)}")
    dash = text.find("-")
    parts = (text if dash == -1 else text[:dash]).split(".")
    if len(parts) > 3:
        invalid(f"expected at most MAJOR.MINOR.PATCH, received {quote(text)}")
    components: list[int] = []
    for i, part in enumerate(parts):
        if part in ("x", "X", "*"):
            continue
        if len(components) < i:
            invalid(f"a version component cannot follow a wildcard, received {quote(text)}")
        components.append(parse_component(part, _LABELS[i]))
    if dash == -1:
        return _Partial(tuple(components))
    if len(components) < 3:
        invalid(f"a pre-release requires MAJOR.MINOR.PATCH, received {quote(text)}")
    prerelease = tuple(map(prerelease_identifier, text[dash + 1 :].split(".")))
    return _Partial(tuple(components), prerelease)


_WHITESPACE = re.compile(r"\s+")


def _parse_set(text: str) -> tuple[_Clause, ...]:
    tokens = [t for t in _WHITESPACE.split(text) if t]
    if not tokens:
        invalid("expected a comparator")
    if len(tokens) == 3 and tokens[1] == "-":
        return (_Hyphen(_parse_partial(tokens[0]), _parse_partial(tokens[2])),)
    out: list[_Clause] = []
    i = 0
    while i < len(tokens):
        operator: Operator | None = next((o for o in _OPERATORS if tokens[i].startswith(o)), None)
        rest = tokens[i][len(operator or "") :]
        # Whitespace may separate an operator from its version, as in ``>= 1.2.3``.
        if not rest and operator is not None and i + 1 < len(tokens):
            i += 1
            rest = tokens[i]
        out.append(_Comparator("=" if operator is None else operator, _parse_partial(rest)))
        i += 1
    return tuple(out)


def _parse_or_raise(text: str) -> SemVerRange:
    if not text.strip():
        return any_
    return SemVerRange(tuple(map(_parse_set, text.split("||"))))


def parse(text: str) -> Result[SemVerRange, SemVerError]:
    """An npm-style range, or the reason it is not one; blank text is ``*``."""
    return try_parse("SemVer range", text, _parse_or_raise)


def parse_unsafe(text: str) -> SemVerRange:
    """``parse``; raises its ``SemVerError``."""
    return _or_raise(parse(text))


type Input = SemVerRange | str


def from_input(value: Input) -> Result[SemVerRange, SemVerError]:
    return Ok(value) if isinstance(value, SemVerRange) else parse(value)


def from_input_unsafe(value: Input) -> SemVerRange:
    return _or_raise(from_input(value))


def _or_raise[A](result: Result[A, SemVerError]) -> A:
    if isinstance(result, Ok):
        return result.value
    raise result.error


# --- constructors ---------------------------------------------------------------------


def _clause(operator: Operator, version: VersionInput) -> _Comparator:
    v = version_from_input_unsafe(version)
    return _Comparator(operator, _Partial((v.major, v.minor, v.patch), v.prerelease))


def _single(operator: Operator, version: VersionInput) -> SemVerRange:
    return SemVerRange(((_clause(operator, version),),))


any_: SemVerRange = SemVerRange(((_Comparator("=", _WILDCARD),),))
"""``*``: every release."""


def exact(version: VersionInput) -> SemVerRange:
    """``=version`` (build metadata dropped); raises ``SemVerError`` for an
    invalid version, as the other constructors do."""
    return _single("=", version)


def greater_than(version: VersionInput) -> SemVerRange:
    return _single(">", version)


def greater_than_or_equal_to(version: VersionInput) -> SemVerRange:
    return _single(">=", version)


def less_than(version: VersionInput) -> SemVerRange:
    return _single("<", version)


def less_than_or_equal_to(version: VersionInput) -> SemVerRange:
    return _single("<=", version)


def caret(version: VersionInput) -> SemVerRange:
    return _single("^", version)


def tilde(version: VersionInput) -> SemVerRange:
    return _single("~", version)


def between(*, minimum: VersionInput, maximum: VersionInput) -> SemVerRange:
    """``>=minimum <=maximum``."""
    return SemVerRange(((_clause(">=", minimum), _clause("<=", maximum)),))


# --- formatting -----------------------------------------------------------------------


def _format_partial(p: _Partial) -> str:
    if not p.components:
        return "*"
    core = ".".join(map(str, p.components))
    return core if not p.prerelease else f"{core}-{'.'.join(map(str, p.prerelease))}"


def _format_clause(c: _Clause) -> str:
    if isinstance(c, _Hyphen):
        return f"{_format_partial(c.start)} - {_format_partial(c.end)}"
    return ("" if c.operator == "=" else c.operator) + _format_partial(c.version)


# --- matching (node-semver's Range desugaring) ----------------------------------------
# ``z`` is the pre-release a wildcard lower bound carries: ``(0,)`` when
# pre-releases are included, so ``>=1.2`` admits ``1.2.0-alpha``.


def _bound(op: _BoundOperator, core: Sequence[int], prerelease: tuple[Identifier, ...]) -> _Bound:
    major, minor, patch = (*core, 0, 0, 0)[:3]
    return _Bound(op, major, minor, patch, prerelease)


def _below(core: Sequence[int]) -> _Bound:
    """Below the first pre-release of ``core``: node-semver's ``<X.Y.Z-0``."""
    return _bound("<", core, (0,))


def _floor(p: _Partial, z: tuple[Identifier, ...]) -> _Bound:
    return _bound(">=", p.components, p.prerelease if len(p.components) == 3 else z)


def _after(components: tuple[int, ...], precision: int) -> tuple[int, ...]:
    head = components[:precision]
    return (*head[:-1], head[-1] + 1)


def _caret(p: _Partial, z: tuple[Identifier, ...]) -> list[_Bound]:
    n = len(p.components)
    if n == 0:
        return []
    precision = next((i + 1 for i, c in enumerate(p.components) if c != 0), n)
    return [_floor(p, z), _below(_after(p.components, precision))]


def _tilde(p: _Partial, z: tuple[Identifier, ...]) -> list[_Bound]:
    n = len(p.components)
    if n == 0:
        return []
    return [_floor(p, z), _below(_after(p.components, min(n, 2)))]


def _x_range(op: _BoundOperator, p: _Partial, z: tuple[Identifier, ...]) -> list[_Bound]:  # noqa: PLR0911
    n = len(p.components)
    if n == 3:
        return [_bound(op, p.components, p.prerelease)]
    if n == 0:
        return [_below((0, 0, 0))] if op in ("<", ">") else []
    match op:
        case "=":
            return [_floor(p, z), _below(_after(p.components, n))]
        case ">":
            return [_bound(">=", _after(p.components, n), z)]
        case ">=":
            return [_floor(p, z)]
        case "<=":
            return [_below(_after(p.components, n))]
        case "<":
            return [_below(p.components)]


def _expand(c: _Clause, include_prerelease: bool) -> list[_Bound]:
    z: tuple[Identifier, ...] = (0,) if include_prerelease else ()
    if isinstance(c, _Hyphen):
        # Unlike ``>=``, a full hyphen lower bound without a pre-release takes ``z`` too.
        lower = (
            [_bound(">=", c.start.components, c.start.prerelease or z)]
            if c.start.components
            else []
        )
        return [*lower, *_x_range("<=", c.end, z)]
    match c.operator:
        case "^":
            return _caret(c.version, z)
        case "~":
            return _tilde(c.version, z)
        case _:
            return _x_range(c.operator, c.version, z)


def _compile(
    sets: tuple[tuple[_Clause, ...], ...], *, include_prerelease: bool
) -> tuple[tuple[_Bound, ...], ...]:
    return tuple(
        tuple(b for c in clauses for b in _expand(c, include_prerelease)) for clauses in sets
    )


def _test_bound(b: _Bound, version: SemVer) -> bool:
    result = compare_core(version, b)
    match b.operator:
        case "=":
            return result == 0
        case "<":
            return result < 0
        case "<=":
            return result <= 0
        case ">":
            return result > 0
        case ">=":
            return result >= 0


__all__ = [
    "Input",
    "Operator",
    "SemVerRange",
    "any_",
    "between",
    "caret",
    "exact",
    "from_input",
    "from_input_unsafe",
    "greater_than",
    "greater_than_or_equal_to",
    "less_than",
    "less_than_or_equal_to",
    "parse",
    "parse_unsafe",
    "tilde",
]
