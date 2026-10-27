"""Exact-value nodes: ``Literal`` (one value) and ``Enum`` (the members of
a Python ``enum.Enum``).

A literal matches a value of its own kind only: ``1`` is not ``True`` nor
``1.0``, as ``typing.Literal[1]`` is neither. ``0.0`` and ``-0.0`` match
each other, and the input is kept (its sign too).
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, replace
from typing import Literal as _Literal

from pyfect._js import js_number
from pyfect.exit import Exit, Success
from pyfect.logger._text import json_quote
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import AST, invalid_type
from pyfect.schema.issue import Issue

type LiteralValue = str | int | float | bool | None


def same_literal(literal: LiteralValue, input: object) -> bool:
    """``input`` is ``literal``: equal and of the same kind."""
    match literal:
        case None:
            return input is None
        case bool():
            return isinstance(input, bool) and input == literal
        case int():
            return isinstance(input, int) and not isinstance(input, bool) and input == literal
        case float():
            return isinstance(input, float) and input == literal
        case str():
            return isinstance(input, str) and input == literal


def format_literal(literal: LiteralValue) -> str:
    """A literal as Effect prints it: strings quoted, ``null``, ``true``."""
    match literal:
        case None:
            return "null"
        case bool():
            return "true" if literal else "false"
        case int() | float():
            return js_number(literal)
        case str():
            return json_quote(literal)


def _require_finite(value: float, what: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"A numeric {what} must be finite, got {js_number(value)}")


@dataclass(frozen=True, slots=True, eq=False)
class Literal(AST):
    """Accepts ``literal`` (Effect's ``Literal``). A non-finite number is
    rejected when the node is made."""

    literal: LiteralValue
    tag = "Literal"

    def __post_init__(self) -> None:
        if isinstance(self.literal, float):
            _require_finite(self.literal, "literal")

    def get_expected(self) -> str:
        return format_literal(self.literal)

    def _parse(self, input: object, options: ParseOptions) -> Exit[object, Issue]:
        if same_literal(self.literal, input):
            return Success(input)
        return invalid_type(self, input, options)


type EnumSide = _Literal["decode", "encode", "type", "encoded"]


@dataclass(frozen=True, slots=True, eq=False)
class Enum(AST):
    """The members of ``enum``, encoded as their values (Effect's ``Enum``,
    whose values are the members). Decoding takes a value (or a member) and
    gives the member; encoding gives the member's value. Values must be
    strings or finite numbers.

    ``side`` says what the node does: ``"decode"`` (value to member),
    ``"encode"`` (member to value), ``"type"`` (members) or ``"encoded"``
    (values). Checks apply to members.
    """

    enum: type[enum.Enum]
    side: EnumSide = "decode"
    tag = "Enum"

    def __post_init__(self) -> None:
        for member in self.enum:
            value: object = member.value
            if not isinstance(value, str | int | float) or isinstance(value, bool):
                raise TypeError(
                    f"An enum value must be a string or a number, got {value!r} ({member!r})"
                )
            if isinstance(value, float):
                _require_finite(value, "enum value")

    @property
    def members(self) -> tuple[enum.Enum, ...]:
        return tuple(self.enum)

    def get_expected(self) -> str:
        if self.side in ("type", "encode"):
            return self.enum.__name__
        return " | ".join(format_literal(m.value) for m in self.enum)

    def parse(self, input: object, options: ParseOptions) -> Exit[object, Issue]:
        if self.side != "encode":
            return AST.parse(self, input, options)
        # Checks describe members: run them on the member, then encode it.
        match replace(self, side="type").parse(input, options):
            case Success(member) if isinstance(member, enum.Enum):
                return Success(member.value)
            case exit:
                return exit

    def _parse(self, input: object, options: ParseOptions) -> Exit[object, Issue]:
        if self.side in ("type", "encode"):
            if isinstance(input, self.enum):
                return Success(input)
            return invalid_type(self, input, options)
        for member in self.enum:
            if input is member or same_literal(member.value, input):
                return Success(member if self.side == "decode" else input)
        return invalid_type(self, input, options)

    def flip(self) -> Enum:
        flipped: dict[EnumSide, EnumSide] = {"decode": "encode", "encode": "decode"}
        side = flipped.get(self.side)
        return self if side is None else replace(self, side=side)

    def to_type(self) -> Enum:
        match self.side:
            case "decode":
                return replace(self, side="type")
            case "encode":
                return replace(self, side="encoded", checks=None)
            case _:
                return self
