"""``Class``: instances of a schema class, encoded as a mapping of their
fields (Effect's class declaration, linked to its struct)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal as _Literal
from typing import Protocol, cast

from pyfect.exit import Exit, Success
from pyfect.exit import die as die_exit
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import AST, Checks, invalid_type
from pyfect.schema.ast._check import collect_issues
from pyfect.schema.ast._objects import Objects
from pyfect.schema.ast._result import ParseResult, flat_map
from pyfect.schema.issue import Composite, Issue, reported

type ClassSide = _Literal["decode", "encode", "type", "encoded"]


class ClassShape(Protocol):
    """What a ``Class`` node needs from a schema class."""

    @property
    def cls(self) -> type: ...

    @property
    def fields(self) -> Objects:
        """The decoding struct of the fields (a tagged class's tag too)."""
        ...

    @property
    def encoded(self) -> AST:
        """The struct's encoded side."""
        ...

    @property
    def checks(self) -> Checks | None:
        """The class's own checks, run on each instance it makes."""
        ...

    def construct(self, values: dict[object, object]) -> object:
        """An instance from parsed values, not checked again."""
        ...

    def values_of(self, instance: object) -> dict[object, object]:
        """The struct value of ``instance`` (a tagged class's tag too)."""
        ...


@dataclass(frozen=True, slots=True, eq=False)
class Class(AST):
    """Instances of ``shape.cls``. ``side`` says what the node does:
    ``"decode"`` (a mapping to an instance), ``"encode"`` (an instance to a
    mapping), ``"type"`` (instances) or ``"encoded"`` (mappings). Checks
    apply to instances."""

    shape: ClassShape
    side: ClassSide = "decode"
    tag = "Class"

    def get_expected(self) -> str:
        return self.shape.cls.__name__

    def expected(self) -> str:
        # Decoding reads a mapping first: name what the struct expects, as
        # Effect does (its identifier names the instances).
        if self.side in ("decode", "encoded"):
            return self.shape.encoded.expected()
        return AST.expected(self)

    def parse(self, input: object, options: ParseOptions) -> ParseResult:
        if self.encoding is not None:
            return AST.parse(self, input, options)
        return self.parse_local(input, options)

    def parse_local(self, input: object, options: ParseOptions) -> ParseResult:
        if self.side != "encode":
            return AST.parse_local(self, input, options)
        # Checks describe instances: run them, then encode the fields.
        shape = self.shape
        return flat_map(
            replace(self, side="type").parse_local(input, options),
            lambda instance: shape.fields.flip().parse(shape.values_of(instance), options),
        )

    def _parse(self, input: object, options: ParseOptions) -> ParseResult:
        match self.side:
            case "type" | "encode":
                if isinstance(input, self.shape.cls):
                    return Success(input)
                return invalid_type(self, input, options)
            case "encoded":
                return self.shape.encoded.parse(input, options)
            case "decode":
                return self._decode(input, options)

    def _decode(self, input: object, options: ParseOptions) -> ParseResult:
        shape = self.shape

        def construct(values: object) -> Exit[object, Issue]:
            try:
                instance = shape.construct(cast("dict[object, object]", values))
            except Exception as defect:
                return die_exit(defect)
            return check_instance(shape, instance, options)

        return flat_map(shape.fields.parse(input, options), construct)

    def _flip(self) -> Class:
        flipped: dict[ClassSide, ClassSide] = {"decode": "encode", "encode": "decode"}
        side = flipped.get(self.side)
        return self if side is None else replace(self, side=side)

    def _to_type(self) -> Class:
        match self.side:
            case "decode":
                return replace(self, side="type")
            case "encode":
                return replace(self, side="encoded", checks=None)
            case _:
                return self


def check_instance(
    shape: ClassShape, instance: object, options: ParseOptions
) -> Exit[object, Issue]:
    """``instance`` after the class's own checks."""
    checks = shape.checks
    if checks is None or options.get("disable_checks"):
        return Success(instance)
    try:
        issues = collect_issues(checks, instance, shape.fields, options)
    except Exception as defect:
        return die_exit(defect)
    if issues is None:
        return Success(instance)
    return fail_exit(Composite(shape.fields, issues, reported(instance, options)))
