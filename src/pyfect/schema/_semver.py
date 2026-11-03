"""``SemVer`` and ``SemVerRange`` declarations and their ``...FromString``
codecs (Effect's), over ``pyfect.semver`` and ``pyfect.semver_range``.
Both are written in JSON as their canonical text."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeIs

from pyfect import semver, semver_range
from pyfect.schema import ast
from pyfect.schema._arbitrary_constraint import ArbitraryConstraint
from pyfect.schema._checks_number import is_between
from pyfect.schema._checks_size import is_between_length
from pyfect.schema._checks_string import is_pattern
from pyfect.schema._codec_links import link
from pyfect.schema._declare import declare
from pyfect.schema._parsed_text import parsed_text
from pyfect.schema._primitives import Int, String
from pyfect.schema._schema import Bottom
from pyfect.schema._transform import DecodeToSchema, decode_to
from pyfect.schema.transformation import Transformation


def _format_version(version: semver.SemVer) -> str:
    return version.format()


def _format_range(range: semver_range.SemVerRange) -> str:
    return range.format()


semver_from_string: Transformation[semver.SemVer, str] = parsed_text(semver.parse, _format_version)
semver_range_from_string: Transformation[semver_range.SemVerRange, str] = parsed_text(
    semver_range.parse, _format_range
)
_VERSION_TEXT = String.annotate(expected="a string that will be decoded as a SemVer")
_RANGE_TEXT = String.annotate(expected="a string that will be decoded as a SemVer range")


def _is_version(value: object) -> TypeIs[semver.SemVer]:
    return isinstance(value, semver.SemVer)


def _is_range(value: object) -> TypeIs[semver_range.SemVerRange]:
    return isinstance(value, semver_range.SemVerRange)


def _version_json(_: tuple[ast.AST, ...]) -> ast.Link:
    return ast.Link(_VERSION_TEXT.ast, semver_from_string)


def _range_json(_: tuple[ast.AST, ...]) -> ast.Link:
    return ast.Link(_RANGE_TEXT.ast, semver_range_from_string)


# Generation (Effect's ``toCodecArbitrary``): versions are built from their
# components, ranges from sets of operator and version clauses (at most
# three of each, so the nested arrays stay within Hypothesis's budget).

_NATURAL = Int.check(is_between(minimum=0, maximum=2**53 - 1)).ast


def _texts(pattern: str) -> ast.AST:
    return String.check(is_pattern(pattern)).ast


def _few(item: ast.AST, minimum: int = 0) -> ast.AST:
    """Arrays of ``item``, short enough that nested ones stay small."""
    return ast.append_checks(ast.Arrays(rest=(item,)), (is_between_length(minimum, 3),))


def _fields(**fields: ast.AST) -> ast.Objects:
    return ast.Objects(tuple(ast.PropertySignature(k, v) for k, v in fields.items()))


_CORE = {
    "major": _NATURAL,
    "minor": _NATURAL,
    "patch": _NATURAL,
    "prerelease": _few(ast.Union((_NATURAL, _texts(r"^[0-9]*[A-Za-z-][0-9A-Za-z-]*$")))),
}
_VERSION = _fields(**_CORE, build=_few(_texts(r"^[0-9A-Za-z-]+$")))
_OPERATORS = ("", "=", "<", "<=", ">", ">=", "~", "^")
_CLAUSE = _fields(operator=ast.Union(tuple(map(ast.Literal, _OPERATORS))), version=_fields(**_CORE))
_SETS = _few(_few(_CLAUSE, 1))


def _version_of(components: Mapping[str, Any]) -> semver.SemVer:
    return semver.make(components)  # pyright: ignore[reportArgumentType]


def _components(version: semver.SemVer) -> Mapping[str, Any]:
    return {
        "major": version.major,
        "minor": version.minor,
        "patch": version.patch,
        "prerelease": version.prerelease,
        "build": version.build,
    }


def _range_of(sets: Sequence[Sequence[Mapping[str, Any]]]) -> semver_range.SemVerRange:
    text = " || ".join(
        " ".join(f"{c['operator']}{_version_of(c['version']).format()}" for c in clauses)
        for clauses in sets
    )
    return semver_range.parse_unsafe(text)


def _no_sets(_: semver_range.SemVerRange) -> Sequence[Sequence[Mapping[str, Any]]]:
    raise TypeError("a SemVerRange's generation link only decodes")


def _version_arbitrary(_: tuple[ast.AST, ...], __: ArbitraryConstraint) -> ast.Link:
    return link(_VERSION, decode=_version_of, encode=_components)


def _range_arbitrary(_: tuple[ast.AST, ...], __: ArbitraryConstraint) -> ast.Link:
    return link(_SETS, decode=_range_of, encode=_no_sets)


SemVer: Bottom[semver.SemVer] = declare(
    _is_version,
    expected="SemVer",
    to_codec_json=_version_json,
    to_codec_arbitrary=_version_arbitrary,
)
"""A ``semver.SemVer`` (Effect's ``SemVer``)."""
SemVerFromString: DecodeToSchema[semver.SemVer, str] = _VERSION_TEXT.pipe(
    decode_to(SemVer, semver_from_string)
)
SemVerRange: Bottom[semver_range.SemVerRange] = declare(
    _is_range,
    expected="SemVerRange",
    to_codec_json=_range_json,
    to_codec_arbitrary=_range_arbitrary,
)
"""A ``semver_range.SemVerRange`` (Effect's ``SemVerRange``)."""
SemVerRangeFromString: DecodeToSchema[semver_range.SemVerRange, str] = _RANGE_TEXT.pipe(
    decode_to(SemVerRange, semver_range_from_string)
)
