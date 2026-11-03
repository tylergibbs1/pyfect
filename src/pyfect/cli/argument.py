"""Positional command-line arguments (Effect's ``Argument``).

An ``Argument[A]`` takes the next positional value(s) and parses an ``A``.
Declare arguments as attributes of a ``Config`` class, in order::

    class Copy(Config):
        source = Argument.file("source", must_exist=True)
        targets = Argument.string("target").variadic(min=1)
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Never, Self, overload

from pyfect import config as config_
from pyfect.cli import param as p
from pyfect.cli._environment import Environment
from pyfect.cli.cli_error import CliError
from pyfect.cli.primitive import FileFormat, PathType
from pyfect.effect import Effect
from pyfect.option import Some
from pyfect.redacted import Redacted
from pyfect.result import Result
from pyfect.schema import Codec
from pyfect.schema.issue import Issue

if TYPE_CHECKING:
    from pyfect.cli.prompt import Prompt


@dataclass(frozen=True, eq=False, slots=True)
class Argument[A]:
    """A positional argument parsing an ``A``. Read on a parsed ``Config``
    it is the value."""

    param: p.Param[A]

    @overload
    def __get__(self, instance: None, owner: type[object]) -> Self: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> A: ...
    def __get__(self, instance: object, owner: type[object]) -> Self | A:
        if instance is None:
            return self
        raise AttributeError(f"{owner.__name__} has no parsed value for this argument")

    def parse(self, args: p.ParsedArgs) -> p.Parsed[A]:
        return self.param.parse(args)

    # --- constructors ---------------------------------------------------------

    @staticmethod
    def string(name: str) -> Argument[str]:
        return Argument(p.string(p.ARGUMENT, name))

    @staticmethod
    def integer(name: str) -> Argument[int]:
        return Argument(p.integer(p.ARGUMENT, name))

    @staticmethod
    def finite(name: str) -> Argument[float]:
        """A float (``129.99``, ``-1e3``); ``nan`` and ``inf`` are refused."""
        return Argument(p.finite(p.ARGUMENT, name))

    @staticmethod
    def date(name: str) -> Argument[datetime]:
        return Argument(p.date(p.ARGUMENT, name))

    @staticmethod
    def choice_with_value[B](name: str, choices: Sequence[tuple[str, B]]) -> Argument[B]:
        return Argument(p.choice_with_value(p.ARGUMENT, name, choices))

    @staticmethod
    def literals[L: str](name: str, choices: Sequence[L]) -> Argument[L]:
        """One of ``choices``; a tuple (``("text", "json")``) keeps the
        literal type, a list widens it to ``str``."""
        return Argument(p.literals(p.ARGUMENT, name, choices))

    @staticmethod
    def path(
        name: str,
        *,
        path_type: PathType = "either",
        must_exist: bool = False,
        type_name: str | None = None,
    ) -> Argument[str]:
        return Argument(
            p.path(
                p.ARGUMENT, name, path_type=path_type, must_exist=must_exist, type_name=type_name
            )
        )

    @staticmethod
    def file(name: str, *, must_exist: bool = False) -> Argument[str]:
        return Argument(p.file(p.ARGUMENT, name, must_exist=must_exist))

    @staticmethod
    def directory(name: str, *, must_exist: bool = False) -> Argument[str]:
        return Argument(p.directory(p.ARGUMENT, name, must_exist=must_exist))

    @staticmethod
    def redacted(name: str) -> Argument[Redacted[str]]:
        return Argument(p.redacted(p.ARGUMENT, name))

    @staticmethod
    def file_text(name: str) -> Argument[str]:
        return Argument(p.file_text(p.ARGUMENT, name))

    @staticmethod
    def file_parse(name: str, *, format: FileFormat | None = None) -> Argument[object]:
        return Argument(p.file_parse(p.ARGUMENT, name, format=format))

    @staticmethod
    def file_schema[B](
        name: str,
        schema: Codec[B, object, Environment, object],
        *,
        format: FileFormat | None = None,
        error_formatter: Callable[[Issue], str] | None = None,
    ) -> Argument[B]:
        return Argument(
            p.file_schema(p.ARGUMENT, name, schema, format=format, error_formatter=error_formatter)
        )

    @staticmethod
    def never() -> Argument[Never]:
        """An argument that never parses."""
        return Argument(p.never(p.ARGUMENT))

    # --- metadata -------------------------------------------------------------

    def with_description(self, description: str) -> Argument[A]:
        return Argument(p.with_description(self.param, description))

    def with_metavar(self, metavar: str) -> Argument[A]:
        """The value's name in help, in place of its type."""
        return Argument(p.with_metavar(self.param, metavar))

    # --- values ---------------------------------------------------------------

    def optional(self) -> Argument[A | None]:
        return Argument(p.optional(self.param))

    @overload
    def with_default[B](self, default: Effect[B, CliError, Environment]) -> Argument[A | B]: ...
    @overload
    def with_default[B](self, default: B) -> Argument[A | B]: ...
    def with_default(self, default: Any) -> Argument[Any]:
        """``default`` (or the effect's value) when the argument is missing."""
        return Argument(p.with_default(self.param, default))

    def with_fallback_config[B](self, config: config_.Config[B]) -> Argument[A | B]:
        return Argument(p.with_fallback_config(self.param, config))

    def with_fallback_prompt[B](
        self, prompt: Prompt[B] | Effect[Prompt[B], CliError, Environment]
    ) -> Argument[A | B]:
        p.require_prompt(prompt)
        return Argument(p.with_fallback_prompt(self.param, prompt))

    def variadic(
        self, *, min: int | None = None, max: int | None = None
    ) -> Argument[tuple[A, ...]]:
        """Every remaining value (between ``min`` and ``max`` of them)."""
        return Argument(p.variadic(self.param, min, max))

    def at_least(self, min: int) -> Argument[tuple[A, ...]]:
        return Argument(p.at_least(self.param, min))

    def at_most(self, max: int) -> Argument[tuple[A, ...]]:
        return Argument(p.at_most(self.param, max))

    def between(self, min: int, max: int) -> Argument[tuple[A, ...]]:
        return Argument(p.between(self.param, min, max))

    def map[B](self, f: Callable[[A], B]) -> Argument[B]:
        return Argument(p.map(self.param, f))

    def map_effect[B](self, f: Callable[[A], Effect[B, CliError, Environment]]) -> Argument[B]:
        return Argument(p.map_effect(self.param, f))

    def map_try_catch[B](
        self, f: Callable[[A], B], on_error: Callable[[Exception], str]
    ) -> Argument[B]:
        return Argument(p.map_try_catch(self.param, f, on_error))

    def filter_map[B](
        self, f: Callable[[A], Some[B] | None], on_none: Callable[[A], str]
    ) -> Argument[B]:
        return Argument(p.filter_map(self.param, f, on_none))

    def filter(self, predicate: Callable[[A], bool], on_false: Callable[[A], str]) -> Argument[A]:
        return Argument(p.filter(self.param, predicate, on_false))

    def with_schema[B](self, schema: Codec[B, A, Environment, object]) -> Argument[B]:
        return Argument(p.with_schema(self.param, schema))

    def or_else[B](self, alternative: Callable[[], Argument[B]]) -> Argument[A | B]:
        return Argument(p.or_else(self.param, lambda: alternative().param))

    def or_else_result[B](self, alternative: Callable[[], Argument[B]]) -> Argument[Result[A, B]]:
        return Argument(p.or_else_result(self.param, lambda: alternative().param))


__all__ = ["Argument"]
