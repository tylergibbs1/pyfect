"""``Arrays``: a sequence with leading elements and a rest (Effect's
``Arrays``): tuples, arrays and everything between.

The leading ``elements`` take the first positions, an optional one only at
the end of them. ``rest`` is empty for a fixed tuple; otherwise its first
node takes any number of values after the elements and the others take the
last positions, after them (``[*elements, *rest[0], *rest[1:]]``).

The input is a ``list`` or a ``tuple``; the output is a new ``tuple``, or a
``list`` when ``mutable``. A position past a fixed tuple's elements is an
``UnexpectedKey``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import cast

from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import AST, invalid_type, issue_of
from pyfect.schema.issue import Composite, Issue, MissingKey, Pointer, UnexpectedKey, reported


@dataclass(frozen=True, slots=True)
class Element:
    """A leading position of values of ``type``; an ``optional`` one may be
    missing (it is then missing from the output too)."""

    type: AST
    optional: bool = False


def _check_order(elements: Sequence[Element], rest: Sequence[AST]) -> None:
    optional = [e.optional for e in elements]
    # A required position after the first optional one: a later element, or
    # a position after the rest.
    if True in optional and (not all(optional[optional.index(True) :]) or len(rest) > 1):
        raise ValueError("A required element cannot follow an optional element. ts(1257)")


@dataclass(frozen=True, slots=True, eq=False)
class Arrays(AST):
    """A sequence of ``elements`` then ``rest`` (see the module)."""

    elements: tuple[Element, ...] = ()
    rest: tuple[AST, ...] = ()
    mutable: bool = False
    """Decode to a ``list`` (else a ``tuple``)."""
    tag = "Arrays"

    def __post_init__(self) -> None:
        _check_order(self.elements, self.rest)

    def get_expected(self) -> str:
        return "array"

    def _parse(self, input: object, options: ParseOptions) -> Exit[object, Issue]:
        if not isinstance(input, list | tuple):
            return invalid_type(self, input, options)
        return _Run(self, cast("Sequence[object]", input), options).run()

    def _map(self, f: Callable[[AST], AST]) -> Arrays:
        elements = tuple(Element(f(e.type), e.optional) for e in self.elements)
        rest = tuple(map(f, self.rest))
        same = all(a.type is b.type for a, b in zip(elements, self.elements, strict=True)) and all(
            a is b for a, b in zip(rest, self.rest, strict=True)
        )
        return self if same else replace(self, elements=elements, rest=rest)

    def flip(self) -> Arrays:
        return self._map(lambda t: t.flip())

    def to_type(self) -> Arrays:
        return self._map(lambda t: t.to_type())


class _Stop(Exception):
    """Parsing stops: the first mismatch under ``errors="first"``."""


class _Defect(Exception):
    def __init__(self, failure: Exit[object, Issue]) -> None:
        self.failure = failure


class _Run:
    """One parse of a sequence (Effect's ``ArrayParserState``)."""

    __slots__ = ("ast", "input", "issues", "options", "out", "tail_threshold")

    def __init__(self, ast: Arrays, input: Sequence[object], options: ParseOptions) -> None:
        self.ast = ast
        self.input = input
        self.options = options
        self.out: list[object] = []
        self.issues: list[Issue] = []
        tail = max(0, len(ast.rest) - 1)
        self.tail_threshold = max(len(ast.elements), len(input) - tail)

    def run(self) -> Exit[object, Issue]:
        try:
            self._parse_all()
        except _Stop:
            pass
        except _Defect as defect:
            return defect.failure
        if self.issues:
            issues = self.issues
            return fail_exit(
                Composite(self.ast, (issues[0], *issues[1:]), reported(self.input, self.options))
            )
        return Success(self.out if self.ast.mutable else tuple(self.out))

    def _position(self, index: int) -> Element:
        ast = self.ast
        if index < len(ast.elements):
            return ast.elements[index]
        if index >= self.tail_threshold:
            return Element(ast.rest[index - self.tail_threshold + 1])
        return Element(ast.rest[0])

    def _parse_all(self) -> None:
        ast, input = self.ast, self.input
        count = len(ast.elements)
        tail = max(0, len(ast.rest) - 1)
        end = max(len(input), count + tail) if ast.rest else count
        for index in range(end):
            position = self._position(index)
            if index < len(input):
                self._value(index, position.type.parse(input[index], self.options))
            elif not position.optional:
                self._report(index, MissingKey(position.type.key_annotations))
        if not ast.rest:
            for index in range(count, len(input)):
                self._report(index, UnexpectedKey(ast, reported(input[index], self.options)))

    def _report(self, index: int, issue: Issue) -> None:
        self.issues.append(Pointer((index,), issue))
        if self.options.get("errors") != "all":
            raise _Stop

    def _value(self, index: int, exit: Exit[object, Issue]) -> None:
        match exit:
            case Success(value):
                self.out.append(value)
            case failure:
                issue = issue_of(failure)
                if issue is None:
                    raise _Defect(failure)
                self._report(index, issue)
