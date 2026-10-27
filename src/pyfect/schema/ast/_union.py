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

from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import AST, issue_of
from pyfect.schema.ast._candidates import CandidateIndex, member_expected
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

    def _parse(self, input: object, options: ParseOptions) -> Exit[object, Issue]:
        candidates = [self.types[i] for i in self.candidates(input)]
        out: Success[object] | None = None
        successes: list[AST] = []
        issues: list[Issue] = []
        for member in candidates:
            match member.parse(input, options):
                case Success() as success:
                    if self.mode == "any_of":
                        return success
                    successes.append(member)
                    if out is not None:
                        return fail_exit(OneOf(self, tuple(successes), reported(input, options)))
                    out = success
                case failure:
                    issue = issue_of(failure)
                    if issue is None:
                        return failure
                    issues.append(issue)
        if out is not None:
            return out
        return fail_exit(AnyOf(self, tuple(issues), reported(input, options)))

    def _map_types(self, f: Callable[[AST], AST]) -> Union:
        types = tuple(map(f, self.types))
        if all(a is b for a, b in zip(types, self.types, strict=True)):
            return self
        return replace(self, types=types)

    def flip(self) -> Union:
        return self._map_types(lambda t: t.flip())

    def to_type(self) -> Union:
        return self._map_types(lambda t: t.to_type())
