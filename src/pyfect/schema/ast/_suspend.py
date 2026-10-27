"""``Suspend``: a node made on first use, for recursive schemas."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import AST
from pyfect.schema.ast._result import ParseResult


@dataclass(frozen=True, slots=True, eq=False)
class Suspend(AST):
    """The node ``thunk`` returns, made once on first use (Effect's
    ``Suspend``): a schema may then refer to itself."""

    thunk: Callable[[], AST]
    _memo: list[AST] = field(default_factory=list[AST], init=False, repr=False)
    tag = "Suspend"

    @property
    def target(self) -> AST:
        if not self._memo:
            self._memo.append(self.thunk())
        return self._memo[0]

    def get_expected(self) -> str:
        return self.target.expected()

    def _parse(self, input: object, options: ParseOptions) -> ParseResult:
        return self.target.parse(input, options)

    def _flip(self) -> Suspend:
        # Lazy: the target is not made until the flipped node is used.
        def flipped() -> AST:
            return self.target.flip()

        return replace(self, thunk=flipped)

    def _to_type(self) -> Suspend:
        def typed() -> AST:
            return self.target.to_type()

        return replace(self, thunk=typed)
