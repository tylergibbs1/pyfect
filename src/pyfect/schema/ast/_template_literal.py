"""``TemplateLiteral``: strings made of ordered parts (Effect's
``TemplateLiteral``), as TypeScript's `` `user_${string}` `` types.

A part is a ``String``, ``Number`` or ``BigInt`` node (its checks kept), a
``Literal`` (its text) or, unchecked, a nested ``TemplateLiteral`` or a
``Union`` of parts; no part may have an encoding. A string matches when it
splits into one segment per part, each matching its part: the split is
greedy (a segment takes as much as it can) and backtracks, as Effect's.
A number part matches finite decimal text (``"+1"``, ``"1e5"``), a bigint
part ``-?digits``.

``template_literal_parser`` is the tuple of the parts' values decoded from
such a string (Effect's ``templateLiteralParser``).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Never

from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import AST, SHARED_BY_COPY, invalid_type, issue_of
from pyfect.schema.ast._check import collect_issues
from pyfect.schema.ast._encoding import to_encoded
from pyfect.schema.ast._keywords import BigInt, Number, String
from pyfect.schema.ast._literal import Literal
from pyfect.schema.ast._result import ParseResult, run_now
from pyfect.schema.ast._union import Union
from pyfect.schema.getter._coerce import to_string
from pyfect.schema.issue import Composite, InvalidValue, Issue, reported

if TYPE_CHECKING:
    from pyfect.schema.ast._arrays import Arrays

FINITE_PATTERN = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[Ee][+-]?\d+)?"
"""Finite decimal text, with an optional exponent (Effect's ``FINITE_PATTERN``)."""
STRING_PATTERN = r"[\s\S]*?"
"""Any text, newlines included (Effect's ``STRING_PATTERN``)."""
BIG_INT_PATTERN = r"-?\d+"
_FINITE = re.compile(f"{FINITE_PATTERN}\\Z", re.ASCII)
_BIG_INT = re.compile(f"{BIG_INT_PATTERN}\\Z", re.ASCII)
_SAFE_INTEGER = 2**53 - 1
_MISMATCH = "a string matching template literal parts"


def _part_path(path: str | int) -> str:
    return f"parts[{path}]" if isinstance(path, int) else path


def _validate(node: AST, path: str | int, validated: set[int]) -> bool:
    """``node`` may be a part; one with an encoding raises ``ValueError``."""
    if id(node) in validated:
        return True
    if node.encoding is not None:
        raise ValueError(f"TemplateLiteral parts cannot have an encoding at {_part_path(path)}")
    match node:
        case String() | Number() | BigInt():
            valid = True
        case Literal():
            valid = node.checks is None
        case TemplateLiteral():
            # Its own parts were validated when it was made.
            valid = node.checks is None
        case Union():
            here = _part_path(path)
            valid = node.checks is None and all(
                _validate(member, f"{here}.types[{i}]", validated)
                for i, member in enumerate(node.types)
            )
        case _:
            return False
    if valid:
        validated.add(id(node))
    return valid


def _passes(node: AST, value: object, options: ParseOptions) -> bool:
    checks = node.checks
    return (
        checks is None
        or bool(options.get("disable_checks"))
        or (collect_issues(checks, value, node, options) is None)
    )


def _number(text: str) -> float:
    value = float(text)
    return int(value) if value.is_integer() and abs(value) <= _SAFE_INTEGER else value


def match_part(node: AST, text: str, options: ParseOptions) -> bool:  # noqa: PLR0911
    """``text`` is a segment of the part ``node`` (Effect's ``matchPart``)."""
    match node:
        case String():
            return _passes(node, text, options)
        case Number():
            return _FINITE.match(text) is not None and _passes(node, _number(text), options)
        case BigInt():
            return _BIG_INT.match(text) is not None and _passes(node, int(text), options)
        case Literal():
            return text == to_string(node.literal)
        case TemplateLiteral():
            return segment(node, text, options) is not None
        case Union():
            return any(match_part(member, text, options) for member in node.types)
        case _:
            return False


@dataclass(frozen=True, slots=True, eq=False)
class TemplateLiteral(AST):
    """A string made of ``parts`` (see the module). A part that cannot be
    one raises ``ValueError`` when the node is made."""

    parts: tuple[AST, ...]
    literals: tuple[str | None, ...] = field(init=False, repr=False, metadata=SHARED_BY_COPY)
    """Each part's text when it is a ``Literal``."""
    suffix_lengths: tuple[int, ...] = field(init=False, repr=False, metadata=SHARED_BY_COPY)
    """The length of the literal text after each position."""
    _segments: list[Arrays] = field(
        default_factory=list["Arrays"], init=False, repr=False, metadata=SHARED_BY_COPY
    )
    tag = "TemplateLiteral"

    def __post_init__(self) -> None:
        validated: set[int] = set()
        for index, part in enumerate(self.parts):
            if not _validate(part, index, validated):
                raise ValueError(f"Invalid TemplateLiteral part {part.tag}")
        literals = tuple(
            to_string(part.literal) if isinstance(part, Literal) else None for part in self.parts
        )
        suffix = [0] * (len(literals) + 1)
        for i in range(len(literals) - 1, -1, -1):
            suffix[i] = suffix[i + 1] + len(literals[i] or "")
        object.__setattr__(self, "literals", literals)
        object.__setattr__(self, "suffix_lengths", tuple(suffix))

    def get_expected(self) -> str:
        return "string"

    @property
    def segments(self) -> Arrays:
        """The tuple of the parts read from their segments' text."""
        if not self._segments:
            from pyfect.schema._template_literal import part_from_string, segments_tuple

            self._segments.append(segments_tuple(tuple(map(part_from_string, self.parts))))
        return self._segments[0]

    def _parse(self, input: object, options: ParseOptions) -> ParseResult:
        if not isinstance(input, str):
            return invalid_type(self, input, options)
        parts = segment(self, input, options)
        if parts is None:
            shown = reported(input, options)
            return fail_exit(
                Composite(self, (InvalidValue({"expected": _MISMATCH}, shown),), shown)
            )
        # The parts have no encodings, so this is an ``Exit``.
        result = run_now(self.segments.parse(tuple(parts), options))
        if isinstance(result, Success):
            return Success(input)
        issue = issue_of(result)
        if issue is None:
            return result
        return fail_exit(Composite(self, (issue,), reported(input, options)))

    def _flip(self) -> AST:
        return self


def segment(node: TemplateLiteral, input: str, options: ParseOptions) -> list[str] | None:
    """``input`` split into one segment per part, or ``None`` when it does
    not match (Effect's ``segmentTemplateLiteralParts``)."""
    parts = node.parts
    literals = node.literals
    size = len(input)
    if any(literal and literal not in input for literal in literals):
        return None
    if node.suffix_lengths[0] > size:
        return None
    out = [""] * len(parts)
    failures: set[int] = set()

    def last_index(anchor: str, start: int) -> int:
        # JavaScript's ``lastIndexOf(anchor, start)``.
        return input.rfind(anchor, 0, max(start, 0) + len(anchor))

    def go(i: int, pos: int) -> bool:
        if i == len(parts):
            return pos == size
        key = i * (size + 1) + pos
        if key in failures:
            return False
        part = parts[i]
        if i == len(parts) - 1:
            text = input[pos:]
            if match_part(part, text, options):
                out[i] = text
                return True
        elif isinstance(part, Literal):
            text = literals[i] or ""
            if input.startswith(text, pos) and go(i + 1, pos + len(text)):
                out[i] = text
                return True
        else:
            maximum = size - node.suffix_lengths[i + 1]
            # A split before a literal need only try where that literal occurs.
            anchor = literals[i + 1]
            end = maximum if anchor is None else last_index(anchor, maximum)
            while end >= pos:
                text = input[pos:end]
                if match_part(part, text, options) and go(i + 1, end):
                    out[i] = text
                    return True
                if end == 0:
                    break
                end = end - 1 if anchor is None else last_index(anchor, end - 1)
        failures.add(key)
        return False

    return out if go(0, 0) else None


def normalize_encoded(nodes: Sequence[AST]) -> tuple[AST, ...]:
    """The encoded sides of ``nodes`` as template parts: a union's members
    may overlap there even when decoding picks one, so every union is
    ``any_of``. A node shared in ``nodes`` (a union's members too) gives one
    shared part."""
    memo: dict[int, AST] = {}

    def union(node: Union) -> AST:
        types = tuple(map(encoded, node.types))
        same = all(a is b for a, b in zip(types, node.types, strict=True))
        return node if same and node.mode == "any_of" else replace(node, types=types, mode="any_of")

    def encoded(node: AST) -> AST:
        done = memo.get(id(node))
        if done is None:
            plain = node.encoding is None and node.checks is None and node.encoding_checks is None
            if isinstance(node, Union) and plain:
                done = union(node)
            else:
                side = to_encoded(node)
                done = union(side) if isinstance(side, Union) and side.checks is None else side
            memo[id(node)] = done
        return done

    return tuple(map(encoded, nodes))


def template_mismatch(input: str, options: ParseOptions) -> Exit[Never, Issue]:
    return fail_exit(InvalidValue({"expected": _MISMATCH}, reported(input, options)))
