"""``Suspend``: a node made on first use, for recursive schemas."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from pyfect._stack import stack_nearly_full, with_fresh_stack
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import AST
from pyfect.schema.ast._result import ParseResult


@dataclass(frozen=True, slots=True, eq=False)
class Suspend(AST):
    """The node ``thunk`` returns, made once on first use (Effect's
    ``Suspend``): a schema may then refer to itself."""

    thunk: Callable[[], AST]
    _memo: list[AST] = field(default_factory=list[AST], init=False, repr=False)
    _typed: list[Suspend] = field(default_factory=list["Suspend"], init=False, repr=False)
    tag = "Suspend"

    @property
    def target(self) -> AST:
        if not self._memo:
            self._memo.append(self.thunk())
        return self._memo[0]

    def get_expected(self) -> str:
        return self.target.expected()

    def _parse(self, input: object, options: ParseOptions) -> ParseResult:
        # The one node through which a parse recurses as deep as its input.
        target = self.target
        if not stack_nearly_full():
            return target.parse(input, options)
        return with_fresh_stack(lambda: target.parse(input, options))

    def _flip(self) -> Suspend:
        # Lazy: the target is not made until the flipped node is used.
        def flipped() -> AST:
            return self.target.flip()

        return replace(self, thunk=flipped)

    def _to_type(self) -> Suspend:
        # Made once, so the decoded side of a recursive schema refers back
        # to itself: a finite graph, as the schema is.
        if not self._typed:

            def typed() -> AST:
                return self.target.to_type()

            decoded = replace(self, thunk=typed)
            decoded._typed.append(decoded)
            self._typed.append(decoded)
        return self._typed[0]
