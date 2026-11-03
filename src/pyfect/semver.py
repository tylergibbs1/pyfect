"""Semantic versions, SemVer 2.0.0 (Effect's ``SemVer``)::

    v = semver.parse_unsafe("1.2.3-rc.1+build")
    v.prerelease          # ("rc", 1)
    v.bump("minor")       # SemVer 1.3.0
    v < semver.parse_unsafe("1.2.3")  # True: a pre-release comes first

``SemVer`` is a frozen dataclass that validates itself: components are
integers from 0 to ``2**53 - 1``, identifiers match ``[0-9A-Za-z-]+``, a
numeric pre-release identifier is an ``int`` (``"2"`` becomes ``2``) without
leading zeros. ``<`` / ``>`` follow the spec's precedence, which ignores
build metadata; ``==`` and ``hash`` include it (Effect's ``Order`` and
``Equivalence``). Bumps follow npm's ``semver.inc``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, Never, NotRequired, Protocol, TypedDict

from pyfect._digits import is_digits
from pyfect._js import js_number
from pyfect._json_text import quote
from pyfect.errors import TaggedError
from pyfect.result import Err, Ok, Result

_MAX_SAFE = 2**53 - 1
_SAFE_DIGITS = len(str(_MAX_SAFE))

type Identifier = str | int
type ReleaseType = Literal[
    "major", "premajor", "minor", "preminor", "patch", "prepatch", "prerelease"
]


@dataclass(eq=False)
class SemVerError(TaggedError):
    """A version or range is invalid; ``input`` is the text that was parsed."""

    message: str
    input: str | None = None

    def __str__(self) -> str:
        return self.message


def invalid(message: str) -> Never:
    """Raise a ``SemVerError`` with ``message``."""
    raise SemVerError(message)


def try_parse[A](label: str, input: str, parse: Callable[[str], A]) -> Result[A, SemVerError]:
    """``parse(input)``, its ``SemVerError`` prefixed with ``Invalid
    <label> "<input>": ``."""
    try:
        return Ok(parse(input))
    except SemVerError as error:
        return Err(SemVerError(f"Invalid {label} {quote(input)}: {error.message}", input))


_IDENTIFIER = re.compile(r"[0-9A-Za-z-]+")


def _check_component(value: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_SAFE:
        invalid(f"{label} must be a non-negative safe integer, received {value}")
    return value


def parse_component(value: str, label: str) -> int:
    """A version component: digits without leading zeros, at most ``2**53 - 1``."""
    if not is_digits(value) or (value[0] == "0" and value != "0"):
        invalid(
            f"{label} must be a non-negative integer without leading zeros, received {quote(value)}"
        )
    if len(value) > _SAFE_DIGITS or int(value) > _MAX_SAFE:
        # JavaScript's ``Number(value)``: 20 digits round, 400 are Infinity.
        invalid(f"{label} must be a non-negative safe integer, received {js_number(float(value))}")
    return int(value)


def prerelease_identifier(identifier: Identifier) -> Identifier:
    """A pre-release identifier, digits read as an ``int``."""
    if isinstance(identifier, int):
        return _check_component(identifier, "numeric pre-release identifier")
    if not _IDENTIFIER.fullmatch(identifier):
        invalid(
            f"pre-release identifier must be non-empty [0-9A-Za-z-], received {quote(identifier)}"
        )
    if is_digits(identifier):
        return parse_component(identifier, "numeric pre-release identifier")
    return identifier


def _build_identifier(identifier: str) -> str:
    if not _IDENTIFIER.fullmatch(identifier):
        invalid(f"build identifier must be non-empty [0-9A-Za-z-], received {quote(identifier)}")
    return identifier


def _sign(a: int | str, b: int | str) -> Literal[-1, 0, 1]:
    return -1 if a < b else 1 if a > b else 0  # pyright: ignore[reportOperatorIssue]


def _compare_prerelease(a: Sequence[Identifier], b: Sequence[Identifier]) -> Literal[-1, 0, 1]:
    if not a:
        return 0 if not b else 1
    if not b:
        return -1
    for x, y in zip(a, b, strict=False):
        if x == y:
            continue
        if isinstance(x, int):
            return _sign(x, y) if isinstance(y, int) else -1
        if isinstance(y, int):
            return 1
        return _sign(x, y)
    return _sign(len(a), len(b))


class Core(Protocol):
    """What precedence reads: a ``SemVer``, or a range's bound."""

    @property
    def major(self) -> int: ...
    @property
    def minor(self) -> int: ...
    @property
    def patch(self) -> int: ...
    @property
    def prerelease(self) -> Sequence[Identifier]: ...


def same_core(a: Core, b: Core) -> bool:
    """Whether MAJOR.MINOR.PATCH are equal."""
    return (a.major, a.minor, a.patch) == (b.major, b.minor, b.patch)


def compare_core(a: Core, b: Core) -> Literal[-1, 0, 1]:
    """Precedence of MAJOR.MINOR.PATCH and the pre-release (build ignored)."""
    return (
        _sign(a.major, b.major)
        or _sign(a.minor, b.minor)
        or _sign(a.patch, b.patch)
        or _compare_prerelease(a.prerelease, b.prerelease)
    )


@dataclass(frozen=True, slots=True)
class SemVer:
    """A validated version; the constructor is Effect's ``make``. ``==``
    compares every part, build included."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[Identifier, ...] = field(default=())
    build: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        _check_component(self.major, "major")
        _check_component(self.minor, "minor")
        _check_component(self.patch, "patch")
        object.__setattr__(self, "prerelease", tuple(map(prerelease_identifier, self.prerelease)))
        object.__setattr__(self, "build", tuple(map(_build_identifier, self.build)))

    def __lt__(self, other: SemVer) -> bool:
        return compare_core(self, other) < 0

    def __le__(self, other: SemVer) -> bool:
        return compare_core(self, other) <= 0

    def __gt__(self, other: SemVer) -> bool:
        return compare_core(self, other) > 0

    def __ge__(self, other: SemVer) -> bool:
        return compare_core(self, other) >= 0

    def __str__(self) -> str:
        return self.format()

    def format(self) -> str:
        """``MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]``."""
        out = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            out += "-" + ".".join(map(str, self.prerelease))
        if self.build:
            out += "+" + ".".join(self.build)
        return out

    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def has_build(self) -> bool:
        return bool(self.build)

    def is_initial_development(self) -> bool:
        """Whether the major version is 0."""
        return self.major == 0

    def with_prerelease(self, prerelease: Sequence[Identifier]) -> SemVer:
        return SemVer(self.major, self.minor, self.patch, tuple(prerelease), self.build)

    def with_build(self, build: Sequence[str]) -> SemVer:
        return SemVer(self.major, self.minor, self.patch, self.prerelease, tuple(build))

    def release(self) -> SemVer:
        """The version without pre-release and build."""
        if not self.prerelease and not self.build:
            return self
        return SemVer(self.major, self.minor, self.patch)

    def bump_major(self) -> SemVer:
        keep = self.minor == 0 and self.patch == 0 and bool(self.prerelease)
        return SemVer(self.major if keep else _increment(self.major, "major"), 0, 0)

    def bump_minor(self) -> SemVer:
        keep = self.patch == 0 and bool(self.prerelease)
        return SemVer(self.major, self.minor if keep else _increment(self.minor, "minor"), 0)

    def bump_patch(self) -> SemVer:
        patch = self.patch if self.prerelease else _increment(self.patch, "patch")
        return SemVer(self.major, self.minor, patch)

    def bump_premajor(self, identifier: str | None = None) -> SemVer:
        return SemVer(_increment(self.major, "major"), 0, 0, _start_prerelease(identifier))

    def bump_preminor(self, identifier: str | None = None) -> SemVer:
        minor = _increment(self.minor, "minor")
        return SemVer(self.major, minor, 0, _start_prerelease(identifier))

    def bump_prepatch(self, identifier: str | None = None) -> SemVer:
        patch = _increment(self.patch, "patch")
        return SemVer(self.major, self.minor, patch, _start_prerelease(identifier))

    def bump_prerelease(self, identifier: str | None = None) -> SemVer:
        if not self.prerelease:
            return self.bump_prepatch(identifier)
        if identifier is not None:
            normalized = prerelease_identifier(identifier)
            if self.prerelease[0] != normalized:
                return SemVer(self.major, self.minor, self.patch, (normalized, 0))
        return SemVer(self.major, self.minor, self.patch, _next_prerelease(self.prerelease))

    def bump(self, release_type: ReleaseType, identifier: str | None = None) -> SemVer:  # noqa: PLR0911
        """The next version of ``release_type``, as npm's ``semver.inc``."""
        match release_type:
            case "major":
                return self.bump_major()
            case "minor":
                return self.bump_minor()
            case "patch":
                return self.bump_patch()
            case "premajor":
                return self.bump_premajor(identifier)
            case "preminor":
                return self.bump_preminor(identifier)
            case "prepatch":
                return self.bump_prepatch(identifier)
            case "prerelease":
                return self.bump_prerelease(identifier)

    def difference(self, that: SemVer) -> ReleaseType | None:  # noqa: PLR0911
        """The release type between the two versions, as npm's
        ``semver.diff``; ``None`` when they have the same precedence."""
        comparison = compare_core(self, that)
        if comparison == 0:
            return None
        low, high = (self, that) if comparison < 0 else (that, self)
        high_pre = bool(high.prerelease)
        if low.prerelease and not high_pre:
            if low.minor == 0 and low.patch == 0:
                return "major"
            if same_core(low, high):
                return "minor" if low.patch == 0 else "patch"
        if self.major != that.major:
            return "premajor" if high_pre else "major"
        if self.minor != that.minor:
            return "preminor" if high_pre else "minor"
        if self.patch != that.patch:
            return "prepatch" if high_pre else "patch"
        return "prerelease"


def _increment(value: int, label: str) -> int:
    if value >= _MAX_SAFE:
        invalid(f"{label} cannot be incremented past Number.MAX_SAFE_INTEGER")
    return value + 1


def _start_prerelease(identifier: str | None) -> tuple[Identifier, ...]:
    return (0,) if identifier is None else (prerelease_identifier(identifier), 0)


def _next_prerelease(prerelease: tuple[Identifier, ...]) -> tuple[Identifier, ...]:
    for i in range(len(prerelease) - 1, -1, -1):
        identifier = prerelease[i]
        if isinstance(identifier, int):
            bumped = _increment(identifier, "pre-release identifier")
            return (*prerelease[:i], bumped, *prerelease[i + 1 :])
    return (*prerelease, 0)


class Components(TypedDict):
    major: int
    minor: int
    patch: int
    prerelease: NotRequired[Sequence[Identifier]]
    build: NotRequired[Sequence[str]]


type Input = SemVer | str | Components


def make(components: Components) -> SemVer:
    """A version from its components; raises ``SemVerError`` when invalid."""
    return SemVer(
        components["major"],
        components["minor"],
        components["patch"],
        tuple(components.get("prerelease", ())),
        tuple(components.get("build", ())),
    )


def _parse_or_raise(text: str) -> SemVer:
    rest, build = text, ()
    plus = rest.find("+")
    if plus != -1:
        build, rest = tuple(map(_build_identifier, rest[plus + 1 :].split("."))), rest[:plus]
    prerelease: tuple[Identifier, ...] = ()
    dash = rest.find("-")
    if dash != -1:
        prerelease = tuple(map(prerelease_identifier, rest[dash + 1 :].split(".")))
        rest = rest[:dash]
    core = rest.split(".")
    if len(core) != 3:
        invalid("expected MAJOR.MINOR.PATCH")
    return SemVer(
        parse_component(core[0], "major"),
        parse_component(core[1], "minor"),
        parse_component(core[2], "patch"),
        prerelease,
        build,
    )


def parse(text: str) -> Result[SemVer, SemVerError]:
    """A SemVer 2.0.0 string, or the reason it is not one."""
    return try_parse("SemVer", text, _parse_or_raise)


def parse_unsafe(text: str) -> SemVer:
    """``parse``; raises its ``SemVerError``."""
    return _or_raise(parse(text))


def from_input(value: Input) -> Result[SemVer, SemVerError]:
    """A version as is, a string parsed, or components checked."""
    if isinstance(value, SemVer):
        return Ok(value)
    if isinstance(value, str):
        return parse(value)
    try:
        return Ok(make(value))
    except SemVerError as error:
        return Err(error)


def from_input_unsafe(value: Input) -> SemVer:
    return _or_raise(from_input(value))


def _or_raise[A](result: Result[A, SemVerError]) -> A:
    match result:
        case Ok(value):
            return value
        case Err(error):
            raise error


__all__ = [
    "Components",
    "Core",
    "Identifier",
    "Input",
    "ReleaseType",
    "SemVer",
    "SemVerError",
    "compare_core",
    "from_input",
    "from_input_unsafe",
    "invalid",
    "make",
    "parse",
    "parse_component",
    "parse_unsafe",
    "prerelease_identifier",
    "same_core",
    "try_parse",
]
