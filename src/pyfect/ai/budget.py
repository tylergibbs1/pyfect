"""Run-wide limits on what a program's language model calls spend: tokens, requests, tool
calls and cost, drawn from one ``Budget`` by every call under it::

    limits = budget.Limits(tool_calls=9, total_tokens=50_000, max_output_tokens=1_000)
    program.pipe(budget.limit(limits))

The budget is in the fiber's context, so forked fibers, concurrent tool calls and agents
run inside a tool's handler draw from it too, whatever model they use. A nested
``limit`` draws from its own budget and from every one around it.

Before a model request, every budget reserves the request's worst case (its estimate of
the prompt's tokens plus ``max_output_tokens``, and what that would cost); the
response's ``usage`` settles it, and the unused part goes back. A request that fails or
is interrupted gives back its tokens and cost and still counts as a request. A tool call
is counted before its handler runs. A reservation that does not fit fails with
``BudgetExceeded`` before the provider is called or the handler runs. Effect has no
counterpart of this module.
"""

from __future__ import annotations

from typing import final

import pyfect as fx
from pyfect._core import Effect
from pyfect._public import publish
from pyfect.ai._budget import (
    Budget,
    BudgetExceeded,
    Cost,
    Current,
    Limits,
    Resource,
    Spent,
    Tokens,
    estimate_input_tokens,
)


def make(limits: Limits) -> Effect[Budget]:
    """A new budget with nothing spent."""
    return fx.sync(lambda: Budget(limits))


@final
class _Provide:
    __slots__ = ("_budget",)

    def __init__(self, budget: Effect[Budget]) -> None:
        self._budget = budget

    def __call__[A, E, R](self, eff: Effect[A, E, R], /) -> Effect[A, E | BudgetExceeded, R]:
        def under(budget: Budget, outer: tuple[Budget, ...]) -> Effect[A, E, R]:
            budgets = outer if budget in outer else (*outer, budget)
            return eff.pipe(fx.provide_service(Current, budgets))

        return self._budget.flat_map(
            lambda budget: fx.service_option(Current).flat_map(
                lambda found: under(budget, () if found is None else found.value)
            )
        )


def provide(budget: Budget) -> _Provide:
    """Every model request and tool call of an effect draws from ``budget``, and from the
    budgets already around it::

        agent.pipe(budget.provide(shared))
    """
    return _Provide(fx.succeed(budget))


def limit(limits: Limits) -> _Provide:
    """``provide`` a new budget of ``limits`` each time the effect runs::

    agent.pipe(budget.limit(budget.Limits(requests=20)))
    """
    return _Provide(make(limits))


__all__ = [
    "Budget",
    "BudgetExceeded",
    "Cost",
    "Limits",
    "Resource",
    "Spent",
    "Tokens",
    "estimate_input_tokens",
    "limit",
    "make",
    "provide",
]

publish(globals())
