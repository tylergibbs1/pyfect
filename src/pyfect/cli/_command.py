"""The command type (Effect's ``Command`` and internal ``cli/internal/command``).

A ``Command[I, C, E, R]`` parses its config ``I``, shares the flags ``C``
with its subcommands, and runs a handler failing with ``E`` and needing
``R``. A command is also an effect: inside a subcommand's handler,
``shared = yield from parent`` reads the parent's parsed shared flags
(adding ``CommandContext[C]`` to the handler's requirements, which
``with_subcommands`` provides).
"""

from __future__ import annotations

import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Generic, Never, TypeVar, cast, overload, override

from pyfect.cli import param as p
from pyfect.cli._config import Config, ConfigInternal, empty_config, parse_config
from pyfect.cli._environment import Environment
from pyfect.cli._settings import GlobalFlag, LogLevel
from pyfect.cli.cli_error import CliError, DuplicateOption, ParseError, ShowHelp, UnexpectedArgument
from pyfect.cli.help_doc import ExampleDoc
from pyfect.context import Context, Tag, TagLike
from pyfect.effect import Effect, fail, gen, provide_service

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect._primitives import Step

In = TypeVar("In")
C_co = TypeVar("C_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)


class CommandContext[S](Tag[S]):
    """A parent command's parsed shared flags, as a requirement of the
    subcommand handlers that read them (``yield from parent``)."""


def _context_tag(name: str) -> type[CommandContext[Any]]:
    return cast(
        "type[CommandContext[Any]]",
        types.new_class(
            f"CommandContext[{name}]", (CommandContext,), {"key": f"pyfect/cli/Command/{name}"}
        ),
    )


@dataclass(frozen=True, slots=True)
class SelectedTokens:
    name: str
    parsed_input: ParsedTokens


@dataclass(frozen=True, slots=True)
class ParsedTokens:
    """A command line split by command level: each level's flag values and
    arguments, the subcommand chosen and the errors found."""

    flags: Mapping[str, tuple[str, ...]]
    arguments: tuple[str, ...]
    subcommand: SelectedTokens | None = None
    errors: tuple[ParseError, ...] = ()


@dataclass(frozen=True, slots=True)
class Selected:
    """A parent's parse when a subcommand was chosen: its shared flags and
    the subcommand's own parse."""

    context: object
    name: str
    result: object


type Example = ExampleDoc
type _Parse = Callable[[Command[Any, Any, Any, Any], ParsedTokens], Effect[Any, CliError, Any]]
type _Handle = Callable[[Any, tuple[str, ...]], Effect[None, Any, Any]]


@dataclass(frozen=True, eq=False, slots=True)
class SubcommandGroup(Generic[E_co, R_co]):
    """Subcommands listed under their own heading in help."""

    group: str
    commands: tuple[Command[Any, Any, E_co, R_co], ...]


def group[EG = Never, RG = Never](
    name: str, *commands: Command[Any, Any, EG, RG]
) -> SubcommandGroup[EG, RG]:
    return SubcommandGroup(name, commands)


@dataclass(frozen=True, slots=True)
class Group:
    group: str | None
    commands: tuple[Command[Any, Any, Any, Any], ...]


def _no_examples(_: tuple[str, ...]) -> tuple[ExampleDoc, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class State:
    name: str
    config: ConfigInternal
    service: type[CommandContext[Any]]
    parse: _Parse
    handle: _Handle
    context_config: ConfigInternal = empty_config
    description: str | None = None
    short_description: str | None = None
    alias: str | None = None
    unlisted: bool = False
    annotations: Context[Any] = field(default_factory=Context[Any])
    global_flags: tuple[GlobalFlag, ...] = ()
    subcommands: tuple[Group, ...] = ()
    resolve_examples: Callable[[tuple[str, ...]], tuple[ExampleDoc, ...]] = _no_examples


def make_parser(
    config: ConfigInternal, *, allow_leftovers: bool = False
) -> Callable[[ParsedTokens], Effect[Config, CliError, Environment]]:
    """Parses ``config``'s params in order from one level's tokens; leftover
    arguments are an ``UnexpectedArgument`` unless allowed."""

    def parse(tokens: ParsedTokens) -> Effect[Config, CliError, Environment]:
        def body():
            values: list[object] = []
            current = tokens.arguments
            for param in config.ordered_params:
                current, value = yield from param.parse(p.ParsedArgs(tokens.flags, current))
                values.append(value)
            if not allow_leftovers and current:
                return (yield from fail(UnexpectedArgument(current)))
            return config.reconstruct(tuple(values))

        return gen(body)

    return parse


def _own_parse(
    command: Command[Any, Any, Any, Any], tokens: ParsedTokens
) -> Effect[Any, CliError, Any]:
    return make_parser(command.state.config)(tokens)


def parse_context(
    command: Command[Any, Any, Any, Any], tokens: ParsedTokens
) -> Effect[Config, CliError, Environment]:
    return make_parser(command.state.context_config, allow_leftovers=True)(tokens)


def _show_help(_: object, path: tuple[str, ...]) -> Effect[None, CliError]:
    return fail(ShowHelp(path))


def _run_handler(handler: Callable[[Any], Effect[object, Any, Any]]) -> _Handle:
    return lambda value, _: handler(value).as_void()


class Command(Effect[C_co, Never, CommandContext[C_co]], Generic[In, C_co, E_co, R_co]):
    """A command: its config ``In`` parsed from the command line, the shared
    flags ``C_co`` its subcommands read, and a handler failing with ``E_co`` and
    needing ``R_co``. Build with ``make`` and run with ``run``."""

    __slots__ = ("state",)

    def __init__(self, state: State) -> None:
        self.state = state

    @override
    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return self.state.service()

    @override
    def __repr__(self) -> str:
        return f"Command({self.state.name!r})"

    def _derive(self, **changes: Any) -> Any:
        return Command[Any, Any, Any, Any](replace(self.state, **changes))

    # --- reading ---------------------------------------------------------------

    @property
    def name(self) -> str:
        return self.state.name

    @property
    def description(self) -> str | None:
        return self.state.description

    @property
    def short_description(self) -> str | None:
        return self.state.short_description

    @property
    def alias(self) -> str | None:
        return self.state.alias

    @property
    def unlisted(self) -> bool:
        return self.state.unlisted

    @property
    def annotations(self) -> Context[Any]:
        return self.state.annotations

    @property
    def examples(self) -> tuple[ExampleDoc, ...]:
        return self.state.resolve_examples((self.state.name,))

    @property
    def subcommands(self) -> tuple[Group, ...]:
        return self.state.subcommands

    # --- combinators -----------------------------------------------------------

    @overload
    def with_handler[EH = Never](
        self, handler: Callable[[In], Effect[object, EH, LogLevel]]
    ) -> Command[In, C_co, EH, Never]: ...
    @overload
    def with_handler[EH = Never, RH = Never](
        self, handler: Callable[[In], Effect[object, EH, LogLevel | RH]]
    ) -> Command[In, C_co, EH, RH]: ...
    def with_handler(
        self, handler: Callable[[In], Effect[object, Any, Any]]
    ) -> Command[In, C_co, Any, Any]:
        """Runs ``handler`` with the parsed config (in place of any handler
        before)."""
        own = _run_handler(handler)
        if self.state.subcommands:
            return self._derive(handle=_dispatch(self.state, own))
        return self._derive(handle=own)

    def validate(
        self, f: Callable[[In], Effect[object, CliError, Environment]]
    ) -> Command[In, C_co, E_co, R_co]:
        """Checks the parsed config before the handler runs; a failure is
        shown with the help, as a parse error is."""
        before = self.state.parse

        def parse(command: Command[Any, Any, Any, Any], tokens: ParsedTokens):
            def check(value: Any) -> Effect[object, CliError, Environment]:
                return f(cast("In", value.context if isinstance(value, Selected) else value))

            return before(command, tokens).tap(check)

        return self._derive(parse=parse)

    @overload
    def with_subcommands[ES = Never](
        self,
        *subcommands: Command[Any, Any, ES, CommandContext[C_co]]
        | SubcommandGroup[ES, CommandContext[C_co]],
    ) -> Command[In | C_co, C_co, E_co | ES, R_co]: ...
    @overload
    def with_subcommands[ES = Never, RS = Never](
        self,
        *subcommands: Command[Any, Any, ES, CommandContext[C_co] | RS]
        | SubcommandGroup[ES, CommandContext[C_co] | RS],
    ) -> Command[In | C_co, C_co, E_co | ES, R_co | RS]: ...
    def with_subcommands(
        self, *subcommands: Command[Any, Any, Any, Any] | SubcommandGroup[Any, Any]
    ) -> Command[Any, Any, Any, Any]:
        """Adds subcommands (grouped ones under their heading in help). A
        chosen subcommand runs in place of this command's handler, with this
        command's shared flags provided to it."""
        flat, groups = _normalize(subcommands)
        check_for_duplicate_flags(self.state, flat, self.state.context_config)
        by_name = {command.name: command for command in flat}
        before = self.state.parse

        def parse(command: Command[Any, Any, Any, Any], tokens: ParsedTokens):
            selected = tokens.subcommand
            sub = None if selected is None else by_name.get(selected.name)
            if selected is None or sub is None:
                return before(command, tokens)

            def body():
                context = yield from parse_context(command, tokens)
                result = yield from sub.state.parse(sub, selected.parsed_input)
                return Selected(context, sub.name, result)

            return gen(body)

        state = replace(self.state, subcommands=groups, parse=parse)
        return Command(replace(state, handle=_dispatch(state, self.state.handle)))

    @overload
    def with_shared_flags[S: Config](
        self: Command[Config, Config, E_co, R_co], shared: type[S]
    ) -> Command[S, S, E_co, R_co]: ...
    @overload
    def with_shared_flags[S: Config](self, shared: type[S]) -> Command[In, S, E_co, R_co]: ...
    def with_shared_flags(self, shared: type[Config]) -> Command[Any, Any, E_co, R_co]:
        """Flags this command parses and its subcommands read (``yield from
        parent``). A command with its own config must subclass ``shared``;
        its own params come first in help."""
        _check_flags_only(shared)
        state = self.state
        own = state.config.config
        if own is Config:
            config = parse_config(shared)
        elif issubclass(own, shared):
            config = parse_config(own, last=tuple(shared.__cli_fields__))
        else:
            raise TypeError(
                f"{own.__name__} must subclass {shared.__name__} to take it as shared flags"
            )
        context = state.context_config.config
        if context is Config or issubclass(shared, context):
            context_config = parse_config(shared)
        elif issubclass(context, shared):
            context_config = state.context_config
        else:
            raise TypeError(f"{shared.__name__} must subclass {context.__name__}")
        if state.subcommands:
            flat = tuple(command for g in state.subcommands for command in g.commands)
            check_for_duplicate_flags(state, flat, context_config)
        return self._derive(config=config, context_config=context_config)

    def with_description(self, description: str) -> Command[In, C_co, E_co, R_co]:
        return self._derive(description=description)

    def with_short_description(self, short_description: str) -> Command[In, C_co, E_co, R_co]:
        """The one-line description in a parent's list of subcommands."""
        return self._derive(short_description=short_description)

    def with_alias(self, alias: str) -> Command[In, C_co, E_co, R_co]:
        """Another name the command is chosen by as a subcommand."""
        return self._derive(alias=alias)

    def with_unlisted(self) -> Command[In, C_co, E_co, R_co]:
        """Parsed when named, but left out of help, completions and
        suggestions (Effect's ``Command.unlisted``)."""
        return self._derive(unlisted=True)

    def annotate[S, T](self, tag: TagLike[S, T], value: S) -> Command[In, C_co, E_co, R_co]:
        """Metadata for custom formatters, in the help doc's ``annotations``."""
        return self._derive(annotations=self.state.annotations.add(tag, value))

    def annotate_merge(self, annotations: Context[Any]) -> Command[In, C_co, E_co, R_co]:
        return self._derive(annotations=self.state.annotations.merge(annotations))

    def with_examples(
        self,
        examples: Sequence[ExampleDoc] | Callable[[tuple[str, ...]], Sequence[ExampleDoc]],
    ) -> Command[In, C_co, E_co, R_co]:
        """Examples shown in help; a function gets the command's path."""
        if callable(examples):
            resolve = examples

            def resolve_examples(path: tuple[str, ...]) -> tuple[ExampleDoc, ...]:
                return tuple(resolve(path))

            return self._derive(resolve_examples=resolve_examples)
        fixed = tuple(examples)

        def fixed_examples(_: tuple[str, ...]) -> tuple[ExampleDoc, ...]:
            return fixed

        return self._derive(resolve_examples=fixed_examples)


def _check_flags_only(shared: type[Config]) -> None:
    arguments = parse_config(shared).arguments
    if arguments:
        names = ", ".join(single.name for arg in arguments for single in arg.singles())
        raise TypeError(f"Shared flags cannot include arguments: {names}")


def _dispatch(state: State, own: _Handle) -> _Handle:
    by_name = {command.name: command for g in state.subcommands for command in g.commands}
    service = state.service

    def handle(value: object, path: tuple[str, ...]) -> Effect[None, Any, Any]:
        if not isinstance(value, Selected):
            return own(value, path)
        child = by_name.get(value.name)
        if child is None:
            return fail(ShowHelp(path))
        run = child.state.handle(value.result, (*path, child.name))
        return run.pipe(provide_service(service, value.context))

    return handle


def _normalize(
    entries: Sequence[Command[Any, Any, Any, Any] | SubcommandGroup[Any, Any]],
) -> tuple[tuple[Command[Any, Any, Any, Any], ...], tuple[Group, ...]]:
    flat: list[Command[Any, Any, Any, Any]] = []
    grouped: dict[str | None, list[Command[Any, Any, Any, Any]]] = {}
    for entry in entries:
        name, commands = (
            (None, (entry,)) if isinstance(entry, Command) else (entry.group, entry.commands)
        )
        for command in commands:
            flat.append(command)
            grouped.setdefault(name, []).append(command)
    groups = [Group(None, tuple(grouped[None]))] if grouped.get(None) else []
    groups += [Group(name, tuple(cmds)) for name, cmds in grouped.items() if name is not None]
    return tuple(flat), tuple(groups)


def check_for_duplicate_flags(
    parent: State, subcommands: Sequence[Command[Any, Any, Any, Any]], context: ConfigInternal
) -> None:
    """Raises ``DuplicateOption`` when a subcommand declares a flag the
    parent shares: the parent would always claim it."""
    names = {single.name for flag in context.flags for single in flag.singles()}
    for sub in subcommands:
        for flag in sub.state.config.flags:
            for single in flag.singles():
                if single.name in names:
                    raise DuplicateOption(single.name, parent.name, sub.name)


# --- make ----------------------------------------------------------------------------


@overload
def make(name: str) -> Command[Config, Config]: ...
@overload
def make[Cfg: Config](name: str, config: type[Cfg]) -> Command[Cfg, Config]: ...
@overload
def make[Cfg: Config, EH = Never](
    name: str, config: type[Cfg], handler: Callable[[Cfg], Effect[object, EH, LogLevel]]
) -> Command[Cfg, Config, EH, Never]: ...
@overload
def make[Cfg: Config, EH = Never, RH = Never](
    name: str, config: type[Cfg], handler: Callable[[Cfg], Effect[object, EH, LogLevel | RH]]
) -> Command[Cfg, Config, EH, RH]: ...
def make(
    name: str,
    config: type[Config] = Config,
    handler: Callable[[Any], Effect[object, Any, Any]] | None = None,
) -> Command[Any, Any, Any, Any]:
    """A command named ``name`` parsing ``config``'s params; without a
    handler, running it shows its help."""
    return Command(
        State(
            name=name,
            config=parse_config(config),
            service=_context_tag(name),
            parse=_own_parse,
            handle=_show_help if handler is None else _run_handler(handler),
        )
    )


__all__ = [
    "Command",
    "CommandContext",
    "Example",
    "Group",
    "ParsedTokens",
    "SelectedTokens",
    "SubcommandGroup",
    "group",
    "make",
    "make_parser",
]
