"""The schema AST (Effect's ``SchemaAST``): one node per kind of value.

A schema object (``Bottom``) wraps one of these. Each node knows the text
of what it expects (``get_expected``, ``"string"``) and parses a value of
its own kind (``parse``). ``annotations`` hold documentation and message
overrides (``identifier``, ``message``, ``expected``, ...), keyed in
snake_case.

Python mappings: ``Number`` accepts ``int`` and ``float`` (JavaScript has one
number type), ``BigInt`` accepts ``int``, ``Null`` is ``None``; ``bool`` is
neither a number nor a bigint. ``Undefined``, ``Void``, ``Symbol``,
``UniqueSymbol`` and ``ObjectKeyword`` have no Python counterpart (one
``None``, no symbols, every value an object) and are not ported.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import ClassVar

from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.issue import InvalidType, Issue, reported

type Annotations = Mapping[str, object]


@dataclass(frozen=True, slots=True, eq=False)
class AST(ABC):
    """A schema node. Nodes compare by identity, as in Effect."""

    annotations: Annotations | None = field(default=None, kw_only=True)
    tag: ClassVar[str]

    @abstractmethod
    def get_expected(self) -> str:
        """What the node itself expects (``"string"``)."""

    def expected(self) -> str:
        """The text ``"Expected <...>"`` messages use: the ``identifier``
        annotation, else ``get_expected()`` (Effect's ``getExpected``)."""
        identifier = (self.annotations or {}).get("identifier")
        return identifier if isinstance(identifier, str) else self.get_expected()

    @abstractmethod
    def parse(self, input: object, options: ParseOptions) -> Exit[object, Issue]:
        """``input`` checked against this node: ``Success`` with the value
        or ``Failure`` with the issue."""

    def flip(self) -> AST:
        """The node that encodes what this one decodes. A node without an
        encoding is its own flip."""
        return self

    def to_type(self) -> AST:
        """The node's decoded side. A node without an encoding is its own."""
        return self

    def __str__(self) -> str:
        return f"<{self.tag}>"


def annotate[N: AST](ast: N, annotations: Annotations) -> N:
    """``ast`` with ``annotations`` merged over its own."""
    return replace(ast, annotations={**(ast.annotations or {}), **annotations})


@dataclass(frozen=True, slots=True, eq=False)
class _Refinement(AST):
    """A node accepting the values a predicate selects, unchanged."""

    def parse(self, input: object, options: ParseOptions) -> Exit[object, Issue]:
        if self.accepts(input):
            return Success(input)
        return _invalid(self, input, options)

    @abstractmethod
    def accepts(self, input: object) -> bool: ...


def _invalid(ast: AST, input: object, options: ParseOptions) -> Failure[Issue]:
    return fail_exit(InvalidType(ast, reported(input, options)))


@dataclass(frozen=True, slots=True, eq=False)
class Never(_Refinement):
    tag = "Never"

    def get_expected(self) -> str:
        return "never"

    def accepts(self, input: object) -> bool:
        return False


@dataclass(frozen=True, slots=True, eq=False)
class Any(_Refinement):
    tag = "Any"

    def get_expected(self) -> str:
        return "any"

    def accepts(self, input: object) -> bool:
        return True


@dataclass(frozen=True, slots=True, eq=False)
class Unknown(_Refinement):
    tag = "Unknown"

    def get_expected(self) -> str:
        return "unknown"

    def accepts(self, input: object) -> bool:
        return True


@dataclass(frozen=True, slots=True, eq=False)
class Null(_Refinement):
    tag = "Null"

    def get_expected(self) -> str:
        return "null"

    def accepts(self, input: object) -> bool:
        return input is None


@dataclass(frozen=True, slots=True, eq=False)
class String(_Refinement):
    tag = "String"

    def get_expected(self) -> str:
        return "string"

    def accepts(self, input: object) -> bool:
        return isinstance(input, str)


@dataclass(frozen=True, slots=True, eq=False)
class Number(_Refinement):
    tag = "Number"

    def get_expected(self) -> str:
        return "number"

    def accepts(self, input: object) -> bool:
        return isinstance(input, int | float) and not isinstance(input, bool)


@dataclass(frozen=True, slots=True, eq=False)
class Boolean(_Refinement):
    tag = "Boolean"

    def get_expected(self) -> str:
        return "boolean"

    def accepts(self, input: object) -> bool:
        return isinstance(input, bool)


@dataclass(frozen=True, slots=True, eq=False)
class BigInt(_Refinement):
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
