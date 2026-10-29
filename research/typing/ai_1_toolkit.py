"""Question: how do a toolkit's tools' names, successes, failures, handler
errors and dependencies flow into a language model response, and can a
handler be checked against its tool?

Q1. ``toolkit(a, b)`` with one TypeVar over ``*tools``: are names and
    results kept per tool?
Q2. Per-arity overloads (``Toolkit[N_co, RP_co, E, R_co]``, ``RP_co`` the union of each
    tool's result parts): does ``part.name == "a"`` narrow ``part.result``?
Q3. ``tool.handler(fn)`` with a self-typed method: is a handler of the
    wrong success, failure or dependency rejected?

Run: ``uv run pyright -p research/typing research/typing/ai_1_toolkit.py``.

Answers:

Q1. No: one TypeVar over ``*tools`` joins the tools, and ``Tool[N_co, P_co, ...]``
    solved against the join keeps only the first tool's arguments (and the
    name widens to ``str`` without a ``LiteralString`` bound).
Q2. Yes, with ``N_co: LiteralString`` and an overload per arity: the result
    union is exact, and comparing ``part.name`` with a literal narrows a
    union of generic dataclasses whose ``name`` is a literal TypeVar; a
    second ``is_failure: Literal[True]`` class narrows again under
    ``part.is_failure is False`` (not under ``not part.is_failure``), and a class pattern
    ``case ToolResultFailure(name="b")`` narrows both at once. The handler
    errors and dependencies take one TypeVar shared by every tool of an
    overload: separate ones that are all ``Never`` join to ``Unknown``.
Q3. Yes when the method takes its tool's types from ``self``
    (``self: Tool[N_co, P_co, S, F_co, Any, R_co]``) and the handler is a ``Callable``
    returning ``Effect[S, F_co | AiError, R_co]``: pyright solves ``self`` first
    and then checks the handler's effect against those types, rejecting a
    wrong success, a wrong failure or a service the tool does not declare.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal, LiteralString, Never, TypeVar, assert_type, overload

import pyfect as fx
from pyfect.context import Tag

N_co = TypeVar("N_co", bound=LiteralString, covariant=True)
P_co = TypeVar("P_co", covariant=True)
S_co = TypeVar("S_co", covariant=True)
F_co = TypeVar("F_co", covariant=True)
HE_co = TypeVar("HE_co", covariant=True)
R_co = TypeVar("R_co", covariant=True)
RP_co = TypeVar("RP_co", covariant=True)


class AiError(Exception):
    pass


class Db(Tag[int]):
    pass


class Other(Tag[int]):
    pass


@dataclass(frozen=True)
class Tool(Generic[N_co, P_co, S_co, F_co, HE_co, R_co]):
    name: N_co

    def handler[NN: LiteralString, PP, SS, FF, RR](
        self: Tool[NN, PP, SS, FF, Any, RR],
        fn: Callable[[PP], fx.Effect[SS, FF | AiError, RR]],
    ) -> Handler[NN]:
        return Handler(self.name)


@dataclass(frozen=True)
class Handler(Generic[N_co]):
    name: N_co


@dataclass(frozen=True)
class ToolResultSuccess(Generic[N_co, S_co]):
    name: N_co
    result: S_co
    is_failure: Literal[False] = False


@dataclass(frozen=True)
class ToolResultFailure(Generic[N_co, F_co]):
    name: N_co
    result: F_co
    is_failure: Literal[True] = True


@dataclass(frozen=True)
class Toolkit(Generic[N_co, RP_co, HE_co, R_co]):
    names: tuple[str, ...]


def tool[NN: LiteralString, PP, SS, FF](
    name: NN, params: type[PP], success: type[SS], failure: type[FF]
) -> Tool[NN, PP, SS, FF, FF, Never]:
    return Tool(name)


N1 = TypeVar("N1", bound=LiteralString)
N2 = TypeVar("N2", bound=LiteralString)
S1 = TypeVar("S1")
S2 = TypeVar("S2")
F1 = TypeVar("F1")
F2 = TypeVar("F2")
E1 = TypeVar("E1")
E2 = TypeVar("E2")
R1 = TypeVar("R1")
R2 = TypeVar("R2")


@overload
def toolkit(
    t1: Tool[N1, Any, S1, F1, E1, R1], /
) -> Toolkit[N1, ToolResultSuccess[N1, S1] | ToolResultFailure[N1, F1], E1, R1]: ...
@overload
def toolkit(
    t1: Tool[N1, Any, S1, F1, E1, R1], t2: Tool[N2, Any, S2, F2, E1, R1], /
) -> Toolkit[
    N1 | N2,
    ToolResultSuccess[N1, S1]
    | ToolResultFailure[N1, F1]
    | ToolResultSuccess[N2, S2]
    | ToolResultFailure[N2, F2],
    E1,
    R1,
]: ...
def toolkit(*tools: Tool[Any, Any, Any, Any, Any, Any]) -> Toolkit[Any, Any, Any, Any]:
    return Toolkit(tuple(t.name for t in tools))


@dataclass(frozen=True)
class Response(Generic[N_co, RP_co]):
    names: list[N_co]
    results: list[RP_co]


def generate[NN: LiteralString, RR, EE, QQ](
    toolkit: Toolkit[NN, RR, EE, QQ],
) -> fx.Effect[Response[NN, RR], AiError | EE, QQ]:
    raise NotImplementedError


a = tool("a", int, str, ValueError)
b = tool("b", str, bytes, KeyError)
kit = toolkit(a, b)
eff = generate(kit)
assert_type(
    eff,
    fx.Effect[
        Response[
            Literal["a", "b"],
            ToolResultSuccess[Literal["a"], str]
            | ToolResultFailure[Literal["a"], ValueError]
            | ToolResultSuccess[Literal["b"], bytes]
            | ToolResultFailure[Literal["b"], KeyError],
        ],
        AiError | ValueError | KeyError,
        Never,
    ],
)


def use(response: Response[Literal["a", "b"], Any]) -> None:
    pass


def narrow(
    part: ToolResultSuccess[Literal["a"], str]
    | ToolResultFailure[Literal["a"], ValueError]
    | ToolResultSuccess[Literal["b"], bytes]
    | ToolResultFailure[Literal["b"], KeyError],
) -> None:
    if part.name == "a":
        if part.is_failure is False:
            assert_type(part.result, str)
        if not part.is_failure:
            assert_type(part.result, str | ValueError)  # `not` does not narrow
    match part:
        case ToolResultFailure(name="b"):
            assert_type(part.result, KeyError)
        case _:
            pass


# Q3 ------------------------------------------------------------------------------------

ok = a.handler(lambda n: fx.succeed(str(n)))
assert_type(ok, Handler[Literal["a"]])
a.handler(lambda n: fx.succeed(n))  # noqa: PLW0108  # pyright: ignore[reportArgumentType]
a.handler(lambda n: fx.fail(KeyError()))  # pyright: ignore[reportArgumentType]
a.handler(lambda n: Other().map(str))  # pyright: ignore[reportArgumentType]
a.handler(lambda n: fx.fail(AiError()))
