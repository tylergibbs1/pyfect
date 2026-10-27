"""The keyword nodes: one kind of value each, accepted unchanged.

Python mappings: ``Number`` accepts ``int`` and ``float`` (JavaScript has one
number type), ``BigInt`` accepts ``int``, ``Null`` is ``None``; ``bool`` is
neither a number nor a bigint.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.schema.ast._base import Refinement


@dataclass(frozen=True, slots=True, eq=False)
class Never(Refinement):
    tag = "Never"

    def get_expected(self) -> str:
        return "never"

    def accepts(self, input: object) -> bool:
        return False


@dataclass(frozen=True, slots=True, eq=False)
class Any(Refinement):
    tag = "Any"

    def get_expected(self) -> str:
        return "any"

    def accepts(self, input: object) -> bool:
        return True


@dataclass(frozen=True, slots=True, eq=False)
class Unknown(Refinement):
    tag = "Unknown"

    def get_expected(self) -> str:
        return "unknown"

    def accepts(self, input: object) -> bool:
        return True


@dataclass(frozen=True, slots=True, eq=False)
class Null(Refinement):
    tag = "Null"

    def get_expected(self) -> str:
        return "null"

    def accepts(self, input: object) -> bool:
        return input is None


@dataclass(frozen=True, slots=True, eq=False)
class String(Refinement):
    tag = "String"

    def get_expected(self) -> str:
        return "string"

    def accepts(self, input: object) -> bool:
        return isinstance(input, str)


@dataclass(frozen=True, slots=True, eq=False)
class Number(Refinement):
    tag = "Number"

    def get_expected(self) -> str:
        return "number"

    def accepts(self, input: object) -> bool:
        return isinstance(input, int | float) and not isinstance(input, bool)


@dataclass(frozen=True, slots=True, eq=False)
class Boolean(Refinement):
    tag = "Boolean"

    def get_expected(self) -> str:
        return "boolean"

    def accepts(self, input: object) -> bool:
        return isinstance(input, bool)


@dataclass(frozen=True, slots=True, eq=False)
class BigInt(Refinement):
    tag = "BigInt"

    def get_expected(self) -> str:
        return "bigint"

    def accepts(self, input: object) -> bool:
        return isinstance(input, int) and not isinstance(input, bool)


never = Never()
any_ = Any()
unknown = Unknown()
null = Null()
string = String()
number = Number()
boolean = Boolean()
big_int = BigInt()
