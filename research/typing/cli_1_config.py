# pyright: strict, reportUnknownParameterType=false, reportUnknownLambdaType=false
"""CLI exp 1: declaring a command's config so pyright infers the parsed value.

Effect builds a command from a record of params (``{ name: Flag.String("name") }``)
and computes the handler's input with a mapped type. Pyright has no mapped types,
so the record would widen to ``dict[str, Flag[str] | Flag[int]]``. Measured here:

(A) a class whose attributes are params, read through ``__get__``:
    ``class Clone(Config): repository = Argument.string("repository")`` gives
    ``Clone().repository: str`` with no annotation written; a combinator's result
    type is the attribute's type (``optional()`` gives ``int | None``,
    ``with_default("main")`` gives ``str``). Nested groups are a descriptor over
    another config class (``database = nested(Database)``).
(B) a TypedDict next to a dict of params is not checked against it (two
    declarations of one thing).
(C) the handler's parameter is inferred from ``make(name, Clone, handler)``,
    lambdas included.
(D) the parent's shared flags reach a subcommand handler as ``yield from parent``,
    typed ``Shared`` and adding ``CommandContext[Shared]`` to R; ``with_subcommands``
    removes it from the children's R through a union-matching overload (exp2), the
    children's errors and services join through one shared TypeVar per slot.
(E) a handler's R loses the built-in ``LogLevel`` setting tag, and only it.
(F) ``with_shared_flags`` on a command without its own config gives ``Shared``
    exactly; on a command with config, the input stays the command's class (which
    must subclass the shared class: checked when the command is built, since a
    TypeVar bound cannot name another TypeVar).
Chosen: (A), with (C)-(F) as below.

Run: uv run pyright -p research/typing research/typing/cli_1_config.py
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Generic, Never, Self, TypeVar, assert_type, overload

A = TypeVar("A", covariant=True)
E = TypeVar("E", covariant=True, default=Never)
R = TypeVar("R", covariant=True, default=Never)


class Effect(Generic[A, E, R]):
    def __iter__(self) -> Generator[Effect[object, E, R], object, A]: ...


def succeed[T](value: T) -> Effect[T]: ...
def fail[X](error: X) -> Effect[Never, X]: ...
def gen[AA, EE = Never, RR = Never](
    f: Callable[[], Generator[Effect[object, EE, RR], object, AA]],
) -> Effect[AA, EE, RR]: ...


class Tag[S]:
    def __new__(cls) -> Effect[S, Never, Self]: ...


class Users(Tag[str]): ...


class LogLevel(Tag[str | None]): ...


class Flag(Generic[A]):
    @overload
    def __get__(self, instance: None, owner: type[object]) -> Self: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> A: ...
    def __get__(self, instance: object, owner: type[object]) -> Self | A: ...

    @staticmethod
    def string(name: str) -> Flag[str]: ...
    @staticmethod
    def integer(name: str) -> Flag[int]: ...
    @staticmethod
    def boolean(name: str) -> Flag[bool]: ...

    def optional(self) -> Flag[A | None]: ...
    def with_default[B](self, value: B) -> Flag[A | B]: ...


class Argument(Generic[A]):
    @overload
    def __get__(self, instance: None, owner: type[object]) -> Self: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> A: ...
    def __get__(self, instance: object, owner: type[object]) -> Self | A: ...

    @staticmethod
    def string(name: str) -> Argument[str]: ...

    def variadic(self) -> Argument[tuple[A, ...]]: ...


class Config: ...


C_ = TypeVar("C_", bound=Config)


class Nested(Generic[A]):
    @overload
    def __get__(self, instance: None, owner: type[object]) -> Self: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> A: ...
    def __get__(self, instance: object, owner: type[object]) -> Self | A: ...


def nested(config: type[C_]) -> Nested[C_]: ...


class Database(Config):
    host = Flag.string("db-host")
    port = Flag.integer("db-port")


class Deploy(Config):
    service = Argument.string("service")
    files = Argument.string("files").variadic()
    retries = Flag.integer("retries").optional()
    branch = Flag.string("branch").with_default("main")
    database = nested(Database)


def read(config: Deploy) -> None:
    assert_type(config.service, str)
    assert_type(config.files, tuple[str, ...])
    assert_type(config.retries, int | None)
    assert_type(config.branch, str)
    assert_type(config.database.port, int)
    assert_type(Deploy.branch, Flag[str])


I = TypeVar("I")
C = TypeVar("C", covariant=True)
E2 = TypeVar("E2")
R2 = TypeVar("R2")


class CommandContext(Generic[A]):
    """The parent's shared flags, as a requirement of a subcommand."""


class Command(Generic[I, C, E, R]):
    def __iter__(self) -> Generator[Effect[object, Never, CommandContext[C]], object, C]: ...

    @overload
    def with_handler[EH = Never](
        self, handler: Callable[[I], Effect[object, EH, LogLevel]]
    ) -> Command[I, C, EH, Never]: ...
    @overload
    def with_handler[EH = Never, RH = Never](
        self, handler: Callable[[I], Effect[object, EH, LogLevel | RH]]
    ) -> Command[I, C, EH, RH]: ...
    def with_handler(self, handler: Callable[[I], Effect[object, Any, Any]]) -> Command[I, C, Any, Any]: ...

    @overload
    def with_subcommands[ES = Never](
        self, *subcommands: Command[Any, Any, ES, CommandContext[C]]
    ) -> Command[I, C, E | ES, R]: ...
    @overload
    def with_subcommands[ES = Never, RS = Never](
        self, *subcommands: Command[Any, Any, ES, CommandContext[C] | RS]
    ) -> Command[I, C, E | ES, R | RS]: ...
    def with_subcommands(self, *subcommands: Command[Any, Any, Any, Any]) -> Command[I, C, Any, Any]: ...

    @overload
    def with_shared_flags[S: Config](self: Command[Config, Config, E, R], shared: type[S]) -> Command[S, S, E, R]: ...
    @overload
    def with_shared_flags[S: Config](self, shared: type[S]) -> Command[I, S, E, R]: ...
    def with_shared_flags(self, shared: type[Config]) -> Command[Any, Any, E, R]: ...


@overload
def make(name: str) -> Command[Config, Config]: ...
@overload
def make[In: Config](name: str, config: type[In]) -> Command[In, Config]: ...
@overload
def make[In: Config, EH = Never](
    name: str, config: type[In], handler: Callable[[In], Effect[object, EH, LogLevel]]
) -> Command[In, Config, EH, Never]: ...
@overload
def make[In: Config, EH = Never, RH = Never](
    name: str, config: type[In], handler: Callable[[In], Effect[object, EH, LogLevel | RH]]
) -> Command[In, Config, EH, RH]: ...
def make(name: str, config: Any = None, handler: Any = None) -> Any: ...


class Shared(Config):
    verbose = Flag.boolean("verbose")


class Clone(Config):
    repository = Argument.string("repository")


class NotFound(Exception): ...


root = make("git").with_shared_flags(Shared)
assert_type(root, Command[Shared, Shared])


def clone_handler(config: Clone):
    shared = yield from root
    assert_type(shared, Shared)
    assert_type(config.repository, str)
    users = yield from Users()
    level = yield from LogLevel()
    if shared.verbose and level and users:
        yield from fail(NotFound())


clone = make("clone", Clone, lambda config: gen(lambda: clone_handler(config)))
assert_type(clone, Command[Clone, Config, NotFound, CommandContext[Shared] | Users])

def status_handler():
    shared = yield from root
    return shared


status = make("status", Config, lambda _: gen(status_handler))
assert_type(status, Command[Config, Config, Never, CommandContext[Shared]])

app = root.with_subcommands(clone, status)
assert_type(app, Command[Shared, Shared, NotFound, Users])

only_context = root.with_subcommands(status)
assert_type(only_context, Command[Shared, Shared, Never, Never])

handled = make("plain", Clone).with_handler(lambda c: succeed(c.repository))
assert_type(handled, Command[Clone, Config, Never, Never])


class Tool(Shared):
    model = Flag.string("model")


tool = make("tool", Tool).with_shared_flags(Shared)
assert_type(tool, Command[Tool, Shared])
