"""``Union``: a value of any (or exactly one) of several nodes.

Members are tried in order. Only candidates are tried (``_candidates.py``):
a ``Literal`` member when the input is its literal, a mapping member with
literal keys (``"_tag": "A"``) when the input holds its values, any other
member when the input's kind (``"string"``, ``"number"``, ...) is one it can
accept. With no candidate the issue is an empty ``AnyOf``
(``Expected "a" | 1``, ``Expected { readonly "_tag": "A", ... } | ...``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Literal as _Literal
from typing import cast, final

from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions, is_constructing
from pyfect.schema.ast._base import AST, issue_of, join_checks
from pyfect.schema.ast._candidates import CandidateIndex, member_expected
from pyfect.schema.ast._result import ParseResult
from pyfect.schema.ast._steps import Abort, Pending, Steps, Stop, Suspended, resume, run_steps
from pyfect.schema.issue import AnyOf, Issue, OneOf, reported

type UnionMode = _Literal["any_of", "one_of"]


@dataclass(frozen=True, slots=True, eq=False)
class Union(AST):
    """A value matching a member: the first one (``mode="any_of"``), or
    exactly one (``"one_of"``, failing with ``OneOf`` when several do)."""

    types: tuple[AST, ...]
    mode: UnionMode = "any_of"
    _index: list[CandidateIndex] = field(
        default_factory=list[CandidateIndex], init=False, repr=False
    )
    tag = "Union"

    @property
    def candidates(self) -> CandidateIndex:
        """The members that may take an input, by index (made on first use)."""
        if not self._index:
            self._index.append(CandidateIndex(self.types))
        return self._index[0]

    def get_expected(self) -> str:
        expected = (self.annotations or {}).get("expected")
        if isinstance(expected, str):
            return expected
        if not self.types:
            return "never"
        return " | ".join(dict.fromkeys(member_expected(t) for t in self.types))

    def _parse(self, input: object, options: ParseOptions) -> ParseResult:
        if self.mode == "one_of":
            return run_steps(_Run(self, input, options, []))
        # The common case without a run's state: the first member that
        # takes the input.
        issues: list[Issue] = []
        candidates = self.candidates(input, is_constructing(options))
        types = self.types
        for n, i in enumerate(candidates):
            result = types[i].parse(input, options)
            if isinstance(result, Success):
                return result
            if isinstance(result, Failure):
                issue = issue_of(result)
                if issue is None:
                    return result
                issues.append(issue)
                continue
            run = _Run(self, input, options, [types[c] for c in candidates])
            run.issues = issues
            return resume(run, n, Pending(result, _Run.member_at(n)))
        return fail_exit(AnyOf(self, tuple(issues), reported(input, options)))

    def map_types(self, f: Callable[[AST], AST]) -> Union:
        """The union with ``f`` applied to each member (itself when none changes)."""
        types = tuple(map(f, self.types))
        if all(a is b for a, b in zip(types, self.types, strict=True)):
            return self
        return replace(self, types=types)

    def _flip(self) -> Union:
        # Checks describe the decoded side: flipped, they check the input.
        flipped = self.map_types(lambda t: t.flip())
        if self.checks is None and self.encoding_checks is None:
            return flipped
        return replace(flipped, checks=self.encoding_checks, encoding_checks=self.checks)

    def _to_type(self) -> Union:
        typed = self.map_types(lambda t: t.to_type())
        if self.encoding_checks is None:
            return typed
        checks = join_checks(self.checks, self.encoding_checks) if typed is self else self.checks
        return replace(typed, checks=checks, encoding_checks=None)


@final
class _Run(Steps["_Run"]):
    """One parse of a union: a step per candidate member, in order."""

    __slots__ = ("ast", "candidates", "input", "issues", "options", "out", "successes")

    def __init__(
        self, ast: Union, input: object, options: ParseOptions, candidates: list[AST]
    ) -> None:
        self.ast = ast
        self.input = input
        self.options = options
        self.candidates = candidates or [
            ast.types[i] for i in ast.candidates(input, is_constructing(options))
        ]
        self.out: Success[object] | Failure[Issue] | None = None
        self.successes: list[AST] = []
        self.issues: list[Issue] = []

    def copy(self) -> _Run:
        other = _Run.__new__(_Run)
        other.ast, other.input, other.options = self.ast, self.input, self.options
        other.candidates, other.out = self.candidates, self.out
        other.successes = list(self.successes)
        other.issues = list(self.issues)
        return other

    def size(self) -> int:
        return len(self.candidates)

    def finish(self) -> Exit[object, Issue]:
        if self.out is not None:
            return self.out
        return fail_exit(AnyOf(self.ast, tuple(self.issues), reported(self.input, self.options)))

    def run_from(self, start: int) -> Suspended[_Run] | None:
        candidates = self.candidates
        for index in range(start, len(candidates)):
            result = candidates[index].parse(self.input, self.options)
            if isinstance(result, (Success, Failure)):
                self._member(index, result)
            else:
                return index, Pending(result, _Run.member_at(index))
        return None

    @staticmethod
    def member_at(index: int) -> Callable[[_Run, Exit[object, Issue]], None]:
        return lambda run, exit: run._member(index, exit)

    def _member(self, index: int, exit: Exit[object, Issue]) -> None:
        if type(exit) is Success:
            if self.ast.mode == "any_of":
                self.out = exit
                raise Stop
            self.successes.append(self.candidates[index])
            if self.out is not None:
                self.out = fail_exit(
                    OneOf(self.ast, tuple(self.successes), reported(self.input, self.options))
                )
                raise Stop
            self.out = exit
            return
        failure = cast("Failure[Issue]", exit)
        issue = issue_of(failure)
        if issue is None:
            raise Abort(failure)
        self.issues.append(issue)
