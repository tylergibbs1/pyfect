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

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from typing import cast, final

from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import (
    AST,
    at_key,
    construct_missing,
    encoded_optional,
    invalid_type,
    issue_of,
)
from pyfect.schema.ast._result import MISSING, ParseResult
from pyfect.schema.ast._steps import Abort, Pending, Steps, Stop, Suspended, run_steps
from pyfect.schema.ast._suspend import Suspend
from pyfect.schema.issue import Composite, Issue, MissingKey, Pointer, UnexpectedKey, reported


@dataclass(frozen=True, slots=True)
class Element:
    """A leading position of values of ``type``; an ``optional`` one may be
    missing (it is then missing from the output too)."""

    type: AST
    optional: bool = False

    def optional_when_encoded(self) -> bool:
        """Whether the position may be missing from the encoded input (it is
        optional, or a decoding default fills it)."""
        return encoded_optional(self.type, optional=self.optional)


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

    def _parse(self, input: object, options: ParseOptions) -> ParseResult:
        if not isinstance(input, list | tuple):
            return invalid_type(self, input, options)
        run = _Run(self, cast("Sequence[object]", input), options)
        return run_steps(run, options.get("concurrency"))

    def map_types(self, f: Callable[[AST], AST]) -> Arrays:
        """The node with ``f`` applied to each element and rest type (itself
        when none changes)."""
        elements = tuple(Element(f(e.type), e.optional) for e in self.elements)
        rest = tuple(map(f, self.rest))
        same = all(a.type is b.type for a, b in zip(elements, self.elements, strict=True)) and all(
            a is b for a, b in zip(rest, self.rest, strict=True)
        )
        return self if same else replace(self, elements=elements, rest=rest)

    def _flip(self) -> Arrays:
        # Checks describe the decoded side: flipped, they check the input.
        flipped = self.map_types(lambda t: t.flip())
        if self.checks is None and self.encoding_checks is None:
            return flipped
        return replace(flipped, checks=self.encoding_checks, encoding_checks=self.checks)

    def _to_type(self) -> Arrays:
        return self.map_types(lambda t: t.to_type())

    def children(self) -> Iterator[AST]:
        for e in self.elements:
            yield e.type
        yield from self.rest

    def _keeps_structural_checks(self) -> bool:
        return True


@final
class _Run(Steps["_Run"]):
    """One parse of a sequence (Effect's ``ArrayParserState``)."""

    __slots__ = ("ast", "end", "input", "issues", "options", "out", "tail_threshold")

    def __init__(self, ast: Arrays, input: Sequence[object], options: ParseOptions) -> None:
        self.ast = ast
        self.input = input
        self.options = options
        self.out: dict[int, object] = {}
        """The value at each position (positions finish in any order when
        children run concurrently)."""
        self.issues: list[Issue] = []
        count = len(ast.elements)
        tail = max(0, len(ast.rest) - 1)
        self.tail_threshold = max(count, len(input) - tail)
        self.end = max(len(input), count + tail) if ast.rest else count

    def copy(self) -> _Run:
        other = _Run.__new__(_Run)
        other.ast, other.input, other.options = self.ast, self.input, self.options
        other.end, other.tail_threshold = self.end, self.tail_threshold
        other.out = dict(self.out)
        other.issues = list(self.issues)
        return other

    def finish(self) -> Exit[object, Issue]:
        if self.issues:
            issues = self.issues
            return fail_exit(
                Composite(self.ast, (issues[0], *issues[1:]), reported(self.input, self.options))
            )
        out = self.out
        values = [out[i] for i in sorted(out)]
        return Success(values if self.ast.mutable else tuple(values))

    def size(self) -> int:
        return self.end

    def _position(self, index: int) -> Element:
        ast = self.ast
        if index < len(ast.elements):
            return ast.elements[index]
        if index >= self.tail_threshold:
            return Element(ast.rest[index - self.tail_threshold + 1])
        return Element(ast.rest[0])

    def run_from(self, start: int) -> Suspended[_Run] | None:
        """Steps: one per position, then the excess check."""
        input, options, out = self.input, self.options, self.out
        n = len(input)
        for index in range(start, self.end):
            position = self._position(index)
            if index < n:
                result = position.type.parse(input[index], options)
                if type(result) is Success and result.value is not MISSING:
                    out[index] = result.value
                    continue
            elif (constructed := construct_missing(position.type, options)) is not None:
                result = constructed
            elif position.type.encoding is not None or isinstance(position.type, Suspend):
                result = position.type.parse(MISSING, options)
            elif position.optional:
                continue
            else:
                self._report(index, MissingKey(position.type.key_annotations))
                continue
            if isinstance(result, (Success, Failure)):
                self._value(index, position, result)
            else:
                return index, Pending(result, _Run.value_at(index, position))
        self._excess()
        return None

    @staticmethod
    def value_at(index: int, position: Element) -> Callable[[_Run, Exit[object, Issue]], None]:
        return lambda run, exit: run._value(index, position, exit)

    def _excess(self) -> None:
        ast, input = self.ast, self.input
        if not ast.rest:
            for index in range(len(ast.elements), len(input)):
                self._report(index, UnexpectedKey(ast, reported(input[index], self.options)))

    def _report(self, index: int, issue: Issue) -> None:
        self.issues.append(Pointer((index,), issue))
        if self.options.get("errors") != "all":
            raise Stop

    def _value(self, index: int, position: Element, exit: Exit[object, Issue]) -> None:
        if type(exit) is Success:
            value = exit.value
            if value is not MISSING:
                self.out[index] = value
            elif not (position.optional or position.type.optional_key):
                self._report(index, MissingKey(position.type.key_annotations))
            return
        failure = cast("Failure[Issue]", exit)
        issue = issue_of(failure)
        if issue is None:
            raise Abort(at_key(self.ast, index, failure, self.input, self.options))
        self._report(index, issue)
