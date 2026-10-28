"""Named command-line options (Effect's ``Flag``): ``--name value``,
``--name=value``, ``-n value``, boolean switches and their ``--no-name``
negations.

A ``Flag[A]`` parses an ``A``. Declare flags as attributes of a ``Config``
class; reading the attribute on the parsed config gives the value, typed::

    class Deploy(Config):
        force = Flag.boolean("force").with_alias("f").with_default(False)
        retries = Flag.integer("retries").optional()

    def handler(config: Deploy): ...  # config.force: bool, config.retries: int | None
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
class Flag[A]:
    """A flag parsing an ``A``. Read on a parsed ``Config`` it is the value."""

    param: p.Param[A]

    @overload
    def __get__(self, instance: None, owner: type[object]) -> Self: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> A: ...
    def __get__(self, instance: object, owner: type[object]) -> Self | A:
        if instance is None:
            return self
        raise AttributeError(f"{owner.__name__} has no parsed value for this flag")

    def parse(self, args: p.ParsedArgs) -> p.Parsed[A]:
        return self.param.parse(args)

    # --- constructors ---------------------------------------------------------

    @staticmethod
    def string(name: str) -> Flag[str]:
        return Flag(p.string(p.FLAG, name))

    @staticmethod
    def boolean(name: str) -> Flag[bool]:
        return Flag(p.boolean(p.FLAG, name))

    @staticmethod
    def integer(name: str) -> Flag[int]:
        return Flag(p.integer(p.FLAG, name))

    @staticmethod
    def finite(name: str) -> Flag[float]:
        return Flag(p.finite(p.FLAG, name))

    @staticmethod
    def date(name: str) -> Flag[datetime]:
        return Flag(p.date(p.FLAG, name))

    @staticmethod
    def choice_with_value[B](name: str, choices: Sequence[tuple[str, B]]) -> Flag[B]:
        return Flag(p.choice_with_value(p.FLAG, name, choices))

    @staticmethod
    def literals[L: str](name: str, choices: Sequence[L]) -> Flag[L]:
        """One of ``choices``; a tuple (``("text", "json")``) keeps the
        literal type, a list widens it to ``str``."""
        return Flag(p.literals(p.FLAG, name, choices))

    @staticmethod
    def path(
        name: str,
        *,
        path_type: PathType = "either",
        must_exist: bool = False,
        type_name: str | None = None,
    ) -> Flag[str]:
        return Flag(
            p.path(p.FLAG, name, path_type=path_type, must_exist=must_exist, type_name=type_name)
        )

    @staticmethod
    def file(name: str, *, must_exist: bool = False) -> Flag[str]:
        return Flag(p.file(p.FLAG, name, must_exist=must_exist))

    @staticmethod
    def directory(name: str, *, must_exist: bool = False) -> Flag[str]:
        return Flag(p.directory(p.FLAG, name, must_exist=must_exist))

    @staticmethod
    def redacted(name: str) -> Flag[Redacted[str]]:
        return Flag(p.redacted(p.FLAG, name))

    @staticmethod
    def file_text(name: str) -> Flag[str]:
        return Flag(p.file_text(p.FLAG, name))

    @staticmethod
    def file_parse(name: str, *, format: FileFormat | None = None) -> Flag[object]:
        return Flag(p.file_parse(p.FLAG, name, format=format))

    @staticmethod
    def file_schema[B](
        name: str,
        schema: Codec[B, object, Environment, object],
        *,
        format: FileFormat | None = None,
        error_formatter: Callable[[Issue], str] | None = None,
    ) -> Flag[B]:
        return Flag(
            p.file_schema(p.FLAG, name, schema, format=format, error_formatter=error_formatter)
        )

    @staticmethod
    def key_value_pair(name: str) -> Flag[dict[str, str]]:
        """``--name key=value`` given one or more times, merged."""
        return Flag(p.key_value_pair(p.FLAG, name))

    @staticmethod
    def never() -> Flag[Never]:
        """A flag that never parses."""
        return Flag(p.never(p.FLAG))

    # --- metadata -------------------------------------------------------------

    def with_alias(self, alias: str) -> Flag[A]:
        """Another name, given with or without dashes (``"f"`` is ``-f``)."""
        return Flag(p.with_alias(self.param, alias))

    def with_description(self, description: str) -> Flag[A]:
        return Flag(p.with_description(self.param, description))

    def with_optional_value(self, value: str) -> Flag[A]:
        """The value ``--name`` takes when given alone."""
        return Flag(p.with_optional_value(self.param, value))

    def with_negation(self, name: str) -> Flag[A]:
        """A boolean flag's negated name, in place of ``no-<name>``."""
        return Flag(p.with_negation(self.param, name))

    def without_negation(self) -> Flag[A]:
        """A boolean flag with no negated form."""
        return Flag(p.with_negation(self.param, False))

    def with_metavar(self, metavar: str) -> Flag[A]:
        """The value's name in help, in place of its type."""
        return Flag(p.with_metavar(self.param, metavar))

    def with_hidden(self) -> Flag[A]:
        """Parsed, but left out of help, completions and suggestions."""
        return Flag(p.with_hidden(self.param))

    # --- values ---------------------------------------------------------------

    def optional(self) -> Flag[A | None]:
        return Flag(p.optional(self.param))

    @overload
    def with_default[B](self, default: Effect[B, CliError, Environment]) -> Flag[A | B]: ...
    @overload
    def with_default[B](self, default: B) -> Flag[A | B]: ...
    def with_default(self, default: Any) -> Flag[Any]:
        """``default`` (or the effect's value) when the flag is not given."""
        return Flag(p.with_default(self.param, default))

    def with_fallback_config[B](self, config: config_.Config[B]) -> Flag[A | B]:
        """The config's value when the flag is not given."""
        return Flag(p.with_fallback_config(self.param, config))

    def with_fallback_prompt[B](
        self, prompt: Prompt[B] | Effect[Prompt[B], CliError, Environment]
    ) -> Flag[A | B]:
        """Asks with ``prompt`` when the flag is not given and the terminal
        can prompt."""
        p.require_prompt(prompt)
        return Flag(p.with_fallback_prompt(self.param, prompt))

    def map[B](self, f: Callable[[A], B]) -> Flag[B]:
        return Flag(p.map(self.param, f))

    def map_effect[B](self, f: Callable[[A], Effect[B, CliError, Environment]]) -> Flag[B]:
        return Flag(p.map_effect(self.param, f))

    def map_try_catch[B](
        self, f: Callable[[A], B], on_error: Callable[[Exception], str]
    ) -> Flag[B]:
        """``f``'s result; an exception it raises becomes an invalid value
        with ``on_error``'s message."""
        return Flag(p.map_try_catch(self.param, f, on_error))

    def filter_map[B](
        self, f: Callable[[A], Some[B] | None], on_none: Callable[[A], str]
    ) -> Flag[B]:
        return Flag(p.filter_map(self.param, f, on_none))

    def filter(self, predicate: Callable[[A], bool], on_false: Callable[[A], str]) -> Flag[A]:
        return Flag(p.filter(self.param, predicate, on_false))

    def with_schema[B](self, schema: Codec[B, A, Environment, object]) -> Flag[B]:
        """The value decoded by ``schema``."""
        return Flag(p.with_schema(self.param, schema))

    def at_least(self, min: int) -> Flag[tuple[A, ...]]:
        """Given ``min`` or more times."""
        return Flag(p.at_least(self.param, min))

    def at_most(self, max: int) -> Flag[tuple[A, ...]]:
        return Flag(p.at_most(self.param, max))

    def between(self, min: int, max: int) -> Flag[tuple[A, ...]]:
        return Flag(p.between(self.param, min, max))

    def or_else[B](self, alternative: Callable[[], Flag[B]]) -> Flag[A | B]:
        """This flag, or else the alternative's (both are recognized)."""
        return Flag(p.or_else(self.param, lambda: alternative().param))

    def or_else_result[B](self, alternative: Callable[[], Flag[B]]) -> Flag[Result[A, B]]:
        """``Ok`` with this flag's value, or else ``Err`` with the
        alternative's."""
        return Flag(p.or_else_result(self.param, lambda: alternative().param))


__all__ = ["Flag"]
