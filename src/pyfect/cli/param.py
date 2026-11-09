"""The parameter tree behind flags and arguments (Effect's ``Param``).

A ``Param[A]`` parses an ``A`` out of a command line's ``ParsedArgs``: the
flag values by flag name and the positional arguments left. ``Single`` is
one named flag or argument; ``Mapped``, ``Transformed``, ``Optional`` and
``Variadic`` wrap it. Programs use ``Flag`` and ``Argument``, which are
typed views of these trees; help, completions and the parser read the
``Single`` nodes through ``extract_single_params``.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Never, cast

from pyfect import config as config_
from pyfect import schema as S
from pyfect._effect_args import wrong_argument
from pyfect._effect_base import EffectBase
from pyfect._js import js_string
from pyfect.cli import primitive as primitive_
from pyfect.cli._environment import Environment
from pyfect.cli.cli_error import (
    CliError,
    InvalidValue,
    MissingArgument,
    MissingOption,
)
from pyfect.cli.primitive import FileFormat, PathType, Primitive
from pyfect.cli.terminal_capabilities import TerminalCapabilities
from pyfect.effect import Effect, fail, gen, succeed
from pyfect.option import Some
from pyfect.redacted import Redacted
from pyfect.result import Err, Ok, Result
from pyfect.schema import Codec
from pyfect.schema.issue import Issue

if TYPE_CHECKING:
    from pyfect.cli.prompt import Prompt

type Kind = Literal["flag", "argument"]
FLAG: Kind = "flag"
ARGUMENT: Kind = "argument"


@dataclass(frozen=True, slots=True)
class ParsedArgs:
    """What a param parses from: the values given for each flag name and
    the positional arguments not yet taken."""

    flags: Mapping[str, Sequence[str]] = field(default_factory=dict[str, Sequence[str]])
    arguments: tuple[str, ...] = ()


type Parsed[A] = Effect[tuple[tuple[str, ...], A], CliError, Environment]
"""The positional arguments left and the value."""
type Parse[A] = Callable[[ParsedArgs], Parsed[A]]


@dataclass(frozen=True, slots=True)
class ParamMetadata:
    is_optional: bool = False
    is_variadic: bool = False
    variadic_min: int | None = None
    variadic_max: int | None = None


class Param[A](ABC):
    """A tree of params parsing an ``A``."""

    kind: Kind

    @abstractmethod
    def parse(self, args: ParsedArgs) -> Parsed[A]: ...

    @abstractmethod
    def map_singles(self, f: Callable[[Single[Any]], Single[Any]]) -> Param[A]:
        """This tree with every ``Single`` in it replaced by ``f``'s."""

    @abstractmethod
    def singles(self) -> list[Single[Any]]:
        """Every ``Single`` in the tree, alternatives included, in order."""

    @abstractmethod
    def metadata(self) -> ParamMetadata:
        """Whether the tree is optional or variadic, and its bounds."""


@dataclass(frozen=True, eq=False)
class Single[A](Param[A]):
    """One named flag or positional argument."""

    kind: Kind
    name: str
    primitive: Primitive[A]
    description: str | None = None
    aliases: tuple[str, ...] = ()
    type_name: str | None = None
    hidden: bool = False
    optional_value: str | None = None
    """The value a flag takes when given without one (``--flag``)."""
    negation: str | Literal[False] | None = None
    """A boolean flag's negated name; ``None`` is ``no-<name>``, ``False``
    none."""

    def parse(self, args: ParsedArgs) -> Parsed[A]:
        if self.kind == ARGUMENT:
            return _parse_positional(self.name, self.primitive, args)
        return _parse_flag(self.name, self.primitive, args)

    def map_singles(self, f: Callable[[Single[Any]], Single[Any]]) -> Param[A]:
        return f(self)

    def singles(self) -> list[Single[Any]]:
        return [self]

    def metadata(self) -> ParamMetadata:
        return ParamMetadata()


@dataclass(frozen=True, eq=False)
class Mapped[X, A](Param[A]):
    param: Param[X]
    f: Callable[[X], A]

    kind: Kind = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", self.param.kind)

    def parse(self, args: ParsedArgs) -> Parsed[A]:
        f = self.f
        return self.param.parse(args).map(lambda parsed: (parsed[0], f(parsed[1])))

    def map_singles(self, f: Callable[[Single[Any]], Single[Any]]) -> Param[A]:
        return Mapped(self.param.map_singles(f), self.f)

    def singles(self) -> list[Single[Any]]:
        return self.param.singles()

    def metadata(self) -> ParamMetadata:
        return self.param.metadata()


type Alternative = Callable[[], Param[Any]]


@dataclass(frozen=True, eq=False)
class Transformed[X, A](Param[A]):
    """A parse built from the inner param's parse and its alternatives'."""

    param: Param[X]
    f: Callable[[Parse[X], tuple[Callable[[], Parse[Any]], ...]], Parse[A]]
    alternatives: tuple[Alternative, ...] = ()

    kind: Kind = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", self.param.kind)

    def parse(self, args: ParsedArgs) -> Parsed[A]:
        parsers = tuple(_lazy_parse(alternative) for alternative in self.alternatives)
        return self.f(self.param.parse, parsers)(args)

    def map_singles(self, f: Callable[[Single[Any]], Single[Any]]) -> Param[A]:
        alternatives = tuple(_mapped_alternative(alt, f) for alt in self.alternatives)
        return Transformed(self.param.map_singles(f), self.f, alternatives)

    def singles(self) -> list[Single[Any]]:
        found = self.param.singles()
        for alternative in self.alternatives:
            found.extend(alternative().singles())
        return found

    def metadata(self) -> ParamMetadata:
        return self.param.metadata()


def _lazy_parse(alternative: Alternative) -> Callable[[], Parse[Any]]:
    return lambda: alternative().parse


def _mapped_alternative(
    alternative: Alternative, f: Callable[[Single[Any]], Single[Any]]
) -> Alternative:
    return lambda: alternative().map_singles(f)


@dataclass(frozen=True, eq=False)
class Optional[X](Param[X | None]):
    param: Param[X]

    kind: Kind = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", self.param.kind)

    def parse(self, args: ParsedArgs) -> Parsed[X | None]:
        missing = (MissingOption, MissingArgument)
        return (
            self.param.parse(args)
            .map(lambda parsed: (parsed[0], cast("X | None", parsed[1])))
            .catch_if(
                lambda error: isinstance(error, missing),
                lambda _: succeed((args.arguments, None)),
            )
        )

    def map_singles(self, f: Callable[[Single[Any]], Single[Any]]) -> Param[X | None]:
        return Optional(self.param.map_singles(f))

    def singles(self) -> list[Single[Any]]:
        return self.param.singles()

    def metadata(self) -> ParamMetadata:
        return replace(self.param.metadata(), is_optional=True)


@dataclass(frozen=True, eq=False)
class Variadic[X](Param[tuple[X, ...]]):
    param: Param[X]
    min: int | None = None
    max: int | None = None

    kind: Kind = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", self.param.kind)

    def parse(self, args: ParsedArgs) -> Parsed[tuple[X, ...]]:
        single = get_underlying_single_or_throw(self.param)
        if single.kind == ARGUMENT:
            return _parse_positional_variadic(self, single, args)
        return _parse_flag_variadic(self, single, args)

    def map_singles(self, f: Callable[[Single[Any]], Single[Any]]) -> Param[tuple[X, ...]]:
        return Variadic(self.param.map_singles(f), self.min, self.max)

    def singles(self) -> list[Single[Any]]:
        return self.param.singles()

    def metadata(self) -> ParamMetadata:
        inner = self.param.metadata()
        return replace(inner, is_variadic=True, variadic_min=self.min, variadic_max=self.max)


# --- parsing -----------------------------------------------------------------


def _parse_positional[A](name: str, primitive: Primitive[A], args: ParsedArgs) -> Parsed[A]:
    if not args.arguments:
        return fail(MissingArgument(name))
    arg = args.arguments[0]
    return primitive.parse(arg).map_both(
        on_failure=lambda expected: cast("CliError", InvalidValue(name, arg, expected, "argument")),
        on_success=lambda value: (args.arguments[1:], value),
    )


def _parse_flag[A](name: str, primitive: Primitive[A], args: ParsedArgs) -> Parsed[A]:
    values = args.flags.get(name)
    if not values:
        return fail(MissingOption(name))
    if len(values) > 1:
        return fail(InvalidValue(name, f"{len(values)} occurrences", "at most 1 value", "flag"))
    arg = values[0]
    return primitive.parse(arg).map_both(
        on_failure=lambda expected: cast("CliError", InvalidValue(name, arg, expected, "flag")),
        on_success=lambda value: (args.arguments, value),
    )


def _plural(n: int) -> str:
    return "" if n == 1 else "s"


def _parse_positional_variadic[X](
    self: Variadic[X], single: Single[Any], args: ParsedArgs
) -> Parsed[tuple[X, ...]]:
    def body():
        results: list[X] = []
        current = args.arguments
        while current and (self.max is None or len(results) < self.max):
            current, value = yield from self.param.parse(ParsedArgs(args.flags, current))
            results.append(value)
        minimum = self.min or 0
        count = len(results)
        if count < minimum:
            if count == 0:
                return (yield from fail(MissingArgument(single.name)))
            return (
                yield from fail(
                    InvalidValue(
                        single.name,
                        f"{count} values",
                        f"at least {minimum} value{_plural(minimum)}",
                        single.kind,
                    )
                )
            )
        return current, tuple(results)

    return gen(body)


def _parse_flag_variadic[X](
    self: Variadic[X], single: Single[Any], args: ParsedArgs
) -> Parsed[tuple[X, ...]]:
    def body():
        values = [
            value for name in (single.name, *single.aliases) for value in args.flags.get(name, ())
        ]
        count = len(values)
        if self.min is not None and count < self.min:
            if count == 0:
                return (yield from fail(MissingOption(single.name)))
            return (
                yield from fail(
                    InvalidValue(
                        single.name,
                        f"{count} occurrences",
                        f"at least {self.min} value{_plural(self.min)}",
                        single.kind,
                    )
                )
            )
        if self.max is not None and count > self.max:
            return (
                yield from fail(
                    InvalidValue(
                        single.name,
                        f"{count} occurrences",
                        f"at most {self.max} value{_plural(self.max)}",
                        single.kind,
                    )
                )
            )
        results: list[X] = []
        for value in values:
            _, parsed = yield from self.param.parse(ParsedArgs({single.name: (value,)}, ()))
            results.append(parsed)
        return args.arguments, tuple(results)

    return gen(body)


# --- tree helpers --------------------------------------------------------------


def extract_single_params(param: Param[Any]) -> list[Single[Any]]:
    """Every ``Single`` in the tree, alternatives included, in order."""
    return param.singles()


def get_underlying_single_or_throw(param: Param[Any]) -> Single[Any]:
    """The tree's one ``Single``; raises ``ValueError`` for none or several."""
    singles = extract_single_params(param)
    if not singles:
        raise ValueError("No Single param found in param structure")
    if len(singles) > 1:
        raise ValueError(f"Multiple Single params found: {', '.join(s.name for s in singles)}")
    return singles[0]


def get_param_metadata(param: Param[Any]) -> ParamMetadata:
    """Whether the tree is optional or variadic, and its bounds."""
    return param.metadata()


# --- combinators ---------------------------------------------------------------

_DASHES = re.compile(r"^-+")


def with_alias[A](param: Param[A], alias: str) -> Param[A]:
    stripped = _DASHES.sub("", alias)
    return param.map_singles(lambda s: replace(s, aliases=(*s.aliases, stripped)))


def with_description[A](param: Param[A], description: str) -> Param[A]:
    return param.map_singles(lambda s: replace(s, description=description))


def with_hidden[A](param: Param[A]) -> Param[A]:
    return param.map_singles(lambda s: replace(s, hidden=True))


def with_metavar[A](param: Param[A], metavar: str) -> Param[A]:
    return param.map_singles(lambda s: replace(s, type_name=metavar))


def with_optional_value[A](param: Param[A], value: str) -> Param[A]:
    return param.map_singles(lambda s: replace(s, optional_value=value))


def with_negation[A](param: Param[A], name: str | Literal[False]) -> Param[A]:
    return param.map_singles(lambda s: replace(s, negation=name))


def map_effect[X, A](
    param: Param[X], f: Callable[[X], Effect[A, CliError, Environment]]
) -> Param[A]:
    def make(parse: Parse[X], _: object) -> Parse[A]:
        def run(args: ParsedArgs) -> Parsed[A]:
            return parse(args).flat_map(
                lambda parsed: f(parsed[1]).map(lambda value: (parsed[0], value))
            )

        return run

    return Transformed(param, make)


def _invalid(single: Single[Any], value: object, expected: str) -> CliError:
    return InvalidValue(single.name, _js_string(value), expected, single.kind)


def _js_string(value: object) -> str:
    """``String(value)`` for the values params produce (a missing one is
    ``undefined``)."""
    return "undefined" if value is None else js_string(value)


def map_try_catch[X, A](
    param: Param[X], f: Callable[[X], A], on_error: Callable[[Exception], str]
) -> Param[A]:
    single = get_underlying_single_or_throw(param)

    def apply(value: X) -> Effect[A, CliError, Environment]:
        try:
            return succeed(f(value))
        except Exception as error:
            return fail(_invalid(single, value, on_error(error)))

    return map_effect(param, apply)


def filter_map[X, A](
    param: Param[X], f: Callable[[X], Some[A] | None], on_none: Callable[[X], str]
) -> Param[A]:
    def apply(value: X) -> Effect[A, CliError, Environment]:
        result = f(value)
        if result is not None:
            return succeed(result.value)
        return fail(_invalid(get_underlying_single_or_throw(param), value, on_none(value)))

    return map_effect(param, apply)


def with_default[A](param: Param[A], default: object) -> Param[Any]:
    optional = Optional(param)
    if isinstance(default, Effect):
        fallback = cast("Effect[Any, CliError, Environment]", default)
        return map_effect(optional, lambda value: fallback if value is None else succeed(value))
    return Mapped(optional, lambda value: default if value is None else value)


def _missing_name(error: MissingOption | MissingArgument) -> tuple[str, Kind]:
    if isinstance(error, MissingOption):
        return error.option, FLAG
    return error.argument, ARGUMENT


def _on_missing[A](
    param: Param[A],
    recover: Callable[[MissingOption | MissingArgument, ParsedArgs], Parsed[Any]],
) -> Param[Any]:
    def make(parse: Parse[A], _: object) -> Parse[Any]:
        def run(args: ParsedArgs) -> Parsed[Any]:
            return parse(args).catch_if(
                lambda error: isinstance(error, (MissingOption, MissingArgument)),
                lambda error: recover(cast("MissingOption | MissingArgument", error), args),
            )

        return run

    return Transformed(param, make)


def with_fallback_config[A](param: Param[A], config: config_.Config[Any]) -> Param[Any]:
    def recover(error: MissingOption | MissingArgument, args: ParsedArgs) -> Parsed[Any]:
        name, kind = _missing_name(error)
        return (
            config_.option(config)
            .map_error(
                lambda config_error: cast(
                    "CliError", InvalidValue(name, "config", config_error.message, kind)
                )
            )
            .flat_map(
                lambda found: (
                    succeed((args.arguments, found.value))
                    if isinstance(found, Some)
                    else cast("Parsed[Any]", fail(error))
                )
            )
        )

    return _on_missing(param, recover)


def require_prompt(value: object) -> None:
    from pyfect.cli import prompt as prompt_

    if not isinstance(value, prompt_.Prompt | EffectBase):
        hint = "to ask, pass a Prompt such as prompt.string(message)"
        raise TypeError(wrong_argument(value, "prompt", "an Effect or a Prompt", hint))


def with_fallback_prompt[A](
    param: Param[A], prompt: Prompt[Any] | Effect[Prompt[Any], CliError, Environment]
) -> Param[Any]:
    from pyfect.cli import prompt as prompt_

    require_prompt(prompt)

    def recover(error: MissingOption | MissingArgument, args: ParsedArgs) -> Parsed[Any]:
        def body():
            capabilities = yield from TerminalCapabilities()
            if not capabilities.can_prompt:
                return (yield from fail(error))
            built = prompt if isinstance(prompt, prompt_.Prompt) else (yield from prompt)
            value = yield from prompt_.run(built).catch_all(
                lambda _: cast("Effect[Never, CliError]", fail(error))
            )
            return args.arguments, value

        return gen(body)

    return _on_missing(param, recover)


def variadic[A](
    param: Param[A], min: int | None = None, max: int | None = None
) -> Param[tuple[A, ...]]:
    get_underlying_single_or_throw(param)
    return Variadic(param, min, max)


def between[A](param: Param[A], min: int, max: int) -> Param[tuple[A, ...]]:
    if min < 0:
        raise ValueError("between: min must be non-negative")
    if max < min:
        raise ValueError("between: max must be greater than or equal to min")
    return variadic(param, min, max)


def at_most[A](param: Param[A], max: int) -> Param[tuple[A, ...]]:
    if max < 0:
        raise ValueError("atMost: max must be non-negative")
    return variadic(param, max=max)


def at_least[A](param: Param[A], min: int) -> Param[tuple[A, ...]]:
    if min < 0:
        raise ValueError("atLeast: min must be non-negative")
    return variadic(param, min=min)


def or_else[A, B](param: Param[A], alternative: Callable[[], Param[B]]) -> Param[A | B]:
    def make(parse: Parse[A], alternatives: tuple[Callable[[], Parse[Any]], ...]) -> Parse[A | B]:
        def run(args: ParsedArgs) -> Parsed[A | B]:
            return parse(args).catch_all(lambda _: alternatives[0]()(args))

        return run

    return Transformed(param, make, (alternative,))


def or_else_result[A, B](
    param: Param[A], alternative: Callable[[], Param[B]]
) -> Param[Result[A, B]]:
    def make(
        parse: Parse[A], alternatives: tuple[Callable[[], Parse[Any]], ...]
    ) -> Parse[Result[A, B]]:
        def run(args: ParsedArgs) -> Parsed[Result[A, B]]:
            return (
                parse(args)
                .map(lambda parsed: (parsed[0], cast("Result[A, B]", Ok(parsed[1]))))
                .catch_all(
                    lambda _: alternatives[0]()(args).map(
                        lambda parsed: (parsed[0], cast("Result[A, B]", Err(parsed[1])))
                    )
                )
            )

        return run

    return Transformed(param, make, (alternative,))


def filter[A](
    param: Param[A], predicate: Callable[[A], bool], on_false: Callable[[A], str]
) -> Param[A]:
    return filter_map(param, lambda value: Some(value) if predicate(value) else None, on_false)


def with_schema[A, B](param: Param[A], schema: Codec[B, A, Environment, object]) -> Param[B]:
    decode = S.decode_unknown_effect(schema)

    def apply(value: A) -> Effect[B, CliError, Environment]:
        single = get_underlying_single_or_throw(param)
        return decode(value).map_error(
            lambda error: cast(
                "CliError",
                InvalidValue(
                    single.name,
                    _js_string(value),
                    f"Schema validation failed: {error.message}",
                    single.kind,
                ),
            )
        )

    return map_effect(param, apply)


def map[X, A](param: Param[X], f: Callable[[X], A]) -> Param[A]:
    return Mapped(param, f)


def optional[A](param: Param[A]) -> Param[A | None]:
    return Optional(param)


# --- constructors ----------------------------------------------------------------


def single[A](kind: Kind, name: str, primitive: Primitive[A]) -> Param[A]:
    return Single(kind, name, primitive)


def string(kind: Kind, name: str) -> Param[str]:
    return Single(kind, name, primitive_.string)


def boolean(kind: Kind, name: str) -> Param[bool]:
    return Single(kind, name, primitive_.boolean)


def integer(kind: Kind, name: str) -> Param[int]:
    return Single(kind, name, primitive_.integer)


def finite(kind: Kind, name: str) -> Param[float]:
    return Single(kind, name, primitive_.finite)


def date(kind: Kind, name: str) -> Param[datetime]:
    return Single(kind, name, primitive_.date_)


def choice_with_value[A](kind: Kind, name: str, choices: Sequence[tuple[str, A]]) -> Param[A]:
    return Single(kind, name, primitive_.choice(choices))


def literals[L: str](kind: Kind, name: str, choices: Sequence[L]) -> Param[L]:
    return choice_with_value(kind, name, [(value, value) for value in choices])


def path(
    kind: Kind,
    name: str,
    *,
    path_type: PathType = "either",
    must_exist: bool = False,
    type_name: str | None = None,
) -> Param[str]:
    return Single(kind, name, primitive_.path(path_type, must_exist), type_name=type_name)


def directory(kind: Kind, name: str, *, must_exist: bool = False) -> Param[str]:
    return path(kind, name, path_type="directory", must_exist=must_exist, type_name="directory")


def file(kind: Kind, name: str, *, must_exist: bool = False) -> Param[str]:
    return path(kind, name, path_type="file", must_exist=must_exist, type_name="file")


def redacted(kind: Kind, name: str) -> Param[Redacted[str]]:
    return Single(kind, name, primitive_.redacted)


def file_text(kind: Kind, name: str) -> Param[str]:
    return Single(kind, name, primitive_.file_text)


def file_parse(kind: Kind, name: str, *, format: FileFormat | None = None) -> Param[object]:
    return Single(kind, name, primitive_.file_parse(format))


def file_schema[A](
    kind: Kind,
    name: str,
    schema: Codec[A, object, Environment, object],
    *,
    format: FileFormat | None = None,
    error_formatter: Callable[[Issue], str] | None = None,
) -> Param[A]:
    return Single(
        kind,
        name,
        primitive_.file_schema(schema, format=format, error_formatter=error_formatter),
    )


def key_value_pair(kind: Kind, name: str) -> Param[dict[str, str]]:
    def merge(pairs: tuple[dict[str, str], ...]) -> dict[str, str]:
        return {key: value for pair in pairs for key, value in pair.items()}

    return Mapped(variadic(Single(kind, name, primitive_.key_value_pair), min=1), merge)


def never(kind: Kind) -> Param[Never]:
    return Single(kind, "__never__", primitive_.never)


__all__ = [
    "ARGUMENT",
    "FLAG",
    "Alternative",
    "Kind",
    "Mapped",
    "Optional",
    "Param",
    "ParamMetadata",
    "Parse",
    "Parsed",
    "ParsedArgs",
    "Single",
    "Transformed",
    "Variadic",
    "at_least",
    "at_most",
    "between",
    "boolean",
    "choice_with_value",
    "date",
    "directory",
    "extract_single_params",
    "file",
    "file_parse",
    "file_schema",
    "file_text",
    "filter",
    "filter_map",
    "finite",
    "get_param_metadata",
    "get_underlying_single_or_throw",
    "integer",
    "key_value_pair",
    "literals",
    "map",
    "map_effect",
    "map_try_catch",
    "never",
    "optional",
    "or_else",
    "or_else_result",
    "path",
    "redacted",
    "require_prompt",
    "single",
    "string",
    "variadic",
    "with_alias",
    "with_default",
    "with_description",
    "with_fallback_config",
    "with_fallback_prompt",
    "with_hidden",
    "with_metavar",
    "with_negation",
    "with_optional_value",
    "with_schema",
]
