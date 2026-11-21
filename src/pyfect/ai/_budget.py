"""The accounting behind ``pyfect.ai.budget``: the budgets' counts, one lock for all of
them, and the hooks ``LanguageModel`` requests and toolkit handlers run through."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, fields
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, final

import pyfect as fx
from pyfect._core import Effect
from pyfect.ai import prompt as P
from pyfect.context import Reference, Tag
from pyfect.errors import TaggedError
from pyfect.exit import Exit, Success
from pyfect.stream import Stream
from pyfect.stream import _constructors as StreamC

if TYPE_CHECKING:
    from pyfect.ai.language_model import EncodedPart, ProviderOptions


type Resource = Literal[
    "requests", "tool_calls", "input_tokens", "output_tokens", "total_tokens", "cost"
]
"""What a budget limits."""


@dataclass(frozen=True)
class Tokens:
    """A request's token counts, as a ``Cost``'s ``price`` gets them."""

    input: int
    output: int


@dataclass(frozen=True)
class Cost:
    """At most ``limit`` spent, a request's tokens costing ``price(tokens)``."""

    limit: Decimal
    price: Callable[[Tokens], Decimal]


def estimate_input_tokens(options: ProviderOptions) -> int:
    """A token per four characters of the prompt's text, tool calls, tool results and
    tool definitions, rounded up."""
    chars = sum(len(tool.name) + len(tool.description or "") for tool in options.tools)
    for message in options.prompt.content:
        if isinstance(message.content, str):
            chars += len(message.content)
            continue
        for part in message.content:
            match part:
                case P.TextPart(text=text) | P.ReasoningPart(text=text):
                    chars += len(text)
                case P.ToolCallPart(name=name, params=params):
                    chars += len(name) + len(repr(params))
                case P.ToolResultPart(name=name, result=result):
                    chars += len(name) + len(repr(result))
                case _:
                    chars += len(repr(part))
    return math.ceil(chars / 4)


@dataclass(frozen=True, kw_only=True)
class Limits:
    """The most a budget spends; ``None`` is no limit. ``max_output_tokens`` is what a
    request reserves for its output, the ``max_tokens`` its provider is configured with:
    a limit on output tokens, total tokens or cost needs it."""

    requests: int | None = None
    tool_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost: Cost | None = None
    max_output_tokens: int = 0
    estimate_input_tokens: Callable[[ProviderOptions], int] = field(
        default=estimate_input_tokens, repr=False
    )

    def __post_init__(self) -> None:
        for name in ("requests", "tool_calls", "input_tokens", "output_tokens", "total_tokens"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"Limits.{name} must not be negative, got {value}")
        if self.cost is not None and self.cost.limit < 0:
            raise ValueError(f"Limits.cost.limit must not be negative, got {self.cost.limit}")
        if self.max_output_tokens < 0:
            raise ValueError(
                f"Limits.max_output_tokens must not be negative, got {self.max_output_tokens}"
            )
        needs_output = self.output_tokens, self.total_tokens, self.cost
        if self.max_output_tokens == 0 and any(limit is not None for limit in needs_output):
            raise ValueError(
                "Limits.max_output_tokens must be set (to the provider's max_tokens) "
                "with a limit on output tokens, total tokens or cost"
            )


@dataclass(frozen=True)
class Spent:
    """What a budget has spent, or holds reserved."""

    requests: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: Decimal = Decimal(0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: Spent) -> Spent:
        return Spent(*(getattr(self, f.name) + getattr(other, f.name) for f in fields(Spent)))

    def __sub__(self, other: Spent) -> Spent:
        return Spent(*(getattr(self, f.name) - getattr(other, f.name) for f in fields(Spent)))


@dataclass(eq=False)
class BudgetExceeded(TaggedError):
    """A reservation did not fit: ``resource`` has ``available`` left of ``limit``, and the
    call needed ``requested``."""

    resource: Resource
    limit: int | Decimal
    requested: int | Decimal
    available: int | Decimal

    def __str__(self) -> str:
        return (
            f"Budget exceeded: {self.resource} needs {self.requested}, "
            f"{self.available} of {self.limit} left"
        )


_lock = threading.Lock()
"""Guards every budget's counts: a reservation checks and holds in all the budgets it
draws from at once, so one lock for all of them keeps that atomic without a lock order."""


@final
class Budget:
    """One budget's counts (made by ``make``)."""

    __slots__ = ("_held", "_spent", "limits")

    limits: Limits

    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self._spent = Spent()
        self._held = Spent()

    def spent(self) -> Effect[Spent]:
        """What settled calls have spent."""
        return fx.sync(lambda: self._spent)

    def held(self) -> Effect[Spent]:
        """What calls in flight hold reserved."""
        return fx.sync(lambda: self._held)

    def _priced(self, requests: int, tool_calls: int, tokens: Tokens) -> Spent:
        cost = self.limits.cost
        price = Decimal(0) if cost is None or tokens == Tokens(0, 0) else cost.price(tokens)
        return Spent(requests, tool_calls, tokens.input, tokens.output, price)

    def _worst(self, options: ProviderOptions) -> Spent:
        estimate = self.limits.estimate_input_tokens(options)
        return self._priced(1, 0, Tokens(estimate, self.limits.max_output_tokens))

    def _exceeded(self, amount: Spent) -> BudgetExceeded | None:
        """Under ``_lock``."""
        limits, used = self.limits, self._spent + self._held
        cost = limits.cost
        limited: list[tuple[Resource, int | Decimal | None, int | Decimal, int | Decimal]] = [
            ("requests", limits.requests, used.requests, amount.requests),
            ("tool_calls", limits.tool_calls, used.tool_calls, amount.tool_calls),
            ("input_tokens", limits.input_tokens, used.input_tokens, amount.input_tokens),
            ("output_tokens", limits.output_tokens, used.output_tokens, amount.output_tokens),
            ("total_tokens", limits.total_tokens, used.total_tokens, amount.total_tokens),
            ("cost", None if cost is None else cost.limit, used.cost, amount.cost),
        ]
        for resource, limit, taken, requested in limited:
            if limit is not None and requested and taken + requested > limit:
                return BudgetExceeded(resource, limit, requested, max(limit - taken, 0))
        return None


@dataclass
class _Hold:
    """What one request holds in each budget, until it settles."""

    amounts: tuple[tuple[Budget, Spent], ...]
    usage: tuple[int | None, int | None] | None = None
    """The response's token counts, once its finish part has come."""


class Current(Tag[tuple[Budget, ...]], key="pyfect/ai/budget/Current"):
    """The budgets a call draws from, outermost first."""


def _claim(
    budgets: Sequence[Budget], amount: Callable[[Budget], Spent], *, hold: bool
) -> Effect[tuple[tuple[Budget, Spent], ...], BudgetExceeded]:
    """Take ``amount`` in every budget or in none: held until settled with ``hold``, else
    spent. Decided in this one step, so no yield comes between the claim and the
    continuation it goes to (CLAUDE.md's claiming rule)."""
    amounts = tuple((b, amount(b)) for b in budgets)
    with _lock:
        for b, a in amounts:
            exceeded = b._exceeded(a)
            if exceeded is not None:
                return fx.fail(exceeded)
        for b, a in amounts:
            if hold:
                b._held += a
            else:
                b._spent += a
    return fx.succeed(amounts)


def _settle(hold: _Hold, ex: Exit[Any, Any]) -> None:
    """Give back what ``hold`` reserved and spend what the request used: the usage its
    response reported (all it reserved where it reported none), or, for a request that
    failed before any usage came, only the request itself. Runs once, as the release of
    the reservation's ``acquire_use_release`` or ``acquire_release``."""
    succeeded = isinstance(ex, Success) or hold.usage is not None
    with _lock:
        for b, reserved in hold.amounts:
            b._held -= reserved
            if succeeded:
                found_input, found_output = hold.usage or (None, None)
                actual = Tokens(
                    reserved.input_tokens if found_input is None else found_input,
                    reserved.output_tokens if found_output is None else found_output,
                )
                b._spent += b._priced(1, 0, actual)
            else:
                b._spent += Spent(requests=1)


def _usage_of(part: EncodedPart) -> tuple[int | None, int | None] | None:
    """The token counts of a finish part (each ``None`` when the provider gave none)."""
    if part.get("type") != "finish":
        return None
    usage: Any = part.get("usage") or {}
    found_input: Any = usage.get("inputTokens") or {}
    found_output: Any = usage.get("outputTokens") or {}

    def count(counts: Any, total: str, pieces: tuple[str, ...]) -> int | None:
        if isinstance(counts.get(total), int):
            return counts[total]
        known = [counts[p] for p in pieces if isinstance(counts.get(p), int)]
        return sum(known) if known else None

    return (
        count(found_input, "total", ("uncached", "cacheRead", "cacheWrite")),
        count(found_output, "total", ("text", "reasoning")),
    )


def _record(hold: _Hold, parts: Sequence[EncodedPart]) -> None:
    for part in parts:
        usage = _usage_of(part)
        if usage is not None:
            hold.usage = usage


def _with_budgets[A, E, R](
    run: Callable[[tuple[Budget, ...]], Effect[A, E, R]], unlimited: Callable[[], Effect[A, E, R]]
) -> Effect[A, E, R]:
    return fx.service_option(Current).flat_map(
        lambda found: unlimited() if found is None else run(found.value)
    )


def metered_request[E, R](
    options: ProviderOptions, request: Callable[[], Effect[Sequence[EncodedPart], E, R]]
) -> Effect[Sequence[EncodedPart], E, R]:
    """``request()`` with a reservation in every current budget (``LanguageModel``'s
    ``generate_text`` and ``generate_object``)."""

    def run(budgets: tuple[Budget, ...]) -> Effect[Sequence[EncodedPart], Any, R]:
        def use(hold: _Hold) -> Effect[Sequence[EncodedPart], E, R]:
            return request().tap(lambda parts: fx.sync(lambda: _record(hold, parts)))

        return fx.acquire_use_release(
            fx.suspend(lambda: _claim(budgets, lambda b: b._worst(options), hold=True)).map(_Hold),
            use,
            lambda hold, ex: fx.sync(lambda: _settle(hold, ex)),
        )

    return _with_budgets(run, request)


def metered_stream[E, R](
    options: ProviderOptions, request: Callable[[], Stream[EncodedPart, E, R]]
) -> Stream[EncodedPart, E, R]:
    """``request()`` with a reservation in every current budget, settled when the stream
    ends, fails or is interrupted (``LanguageModel``'s ``stream_text``)."""

    def run(budgets: tuple[Budget, ...]) -> Effect[Stream[EncodedPart, E, R], Any, Any]:
        def stream(hold: _Hold) -> Stream[EncodedPart, E, R]:
            def recorded(chunk: tuple[EncodedPart, ...]) -> tuple[EncodedPart, ...]:
                _record(hold, chunk)
                return chunk

            return request().map_array(recorded)

        reserved = fx.suspend(lambda: _claim(budgets, lambda b: b._worst(options), hold=True)).map(
            _Hold
        )
        return fx.acquire_release(
            reserved, lambda hold, ex: fx.sync(lambda: _settle(hold, ex))
        ).map(stream)

    return StreamC.scoped(StreamC.unwrap(_with_budgets(run, lambda: fx.succeed(request()))))


class Precounted(Reference[str | None], key="pyfect/ai/budget/Precounted"):
    """The id of the tool call its caller already counted (``pyfect.ai.durable`` counts
    each call before the activity that runs it, so a replayed call counts too)."""

    @classmethod
    def default(cls) -> str | None:
        return None


def tool_call(tool_call_id: str | None = None) -> Effect[object, BudgetExceeded]:
    """Count one tool call in every current budget, before its handler runs, unless it is
    the ``Precounted`` one. The claim is the last step, so what it decided goes straight
    to the caller's continuation."""
    count = _with_budgets(
        lambda budgets: fx.suspend(
            lambda: _claim(budgets, lambda _: Spent(tool_calls=1), hold=False)
        ),
        lambda: fx.void,
    )
    if tool_call_id is None:
        return count
    return Precounted().flat_map(lambda counted: fx.void if counted == tool_call_id else count)
