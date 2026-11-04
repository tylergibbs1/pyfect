"""Commands and running them (Effect's ``Command``).

``make(name, Config, handler)`` builds a command; ``with_subcommands``,
``with_shared_flags`` and the other methods refine it; ``run`` parses the
process arguments (from ``Stdio``) and runs the chosen handler, showing
help and errors the way Effect's CLI does::

    class Greet(Config):
        name = Argument.string("name")

    greet = command.make("greet", Greet, lambda c: console.log(f"Hello, {c.name}"))
    program = command.run(greet, version="1.0.0")

Combinators that remove services from a command's requirements are
curried, for ``.pipe``: ``provide``, ``provide_sync``, ``provide_effect``
and ``with_global_flags``.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from typing import Any, Never, cast, overload

from pyfect import console
from pyfect.cli import _wizard as wizard_
from pyfect.cli import prompt
from pyfect.cli._command import (
    Command,
    CommandContext,
    Example,
    ParsedTokens,
    Selected,
    SubcommandGroup,
    group,
    make,
)
from pyfect.cli._config import Config
from pyfect.cli._environment import Environment
from pyfect.cli._help import flag_of, global_flags_for_path, global_flags_for_tree, help_for_path
from pyfect.cli._lexer import LexResult, lex
from pyfect.cli._parser import (
    consume_global_flags,
    create_flag_registry,
    get_command_path,
    parse_args,
)
from pyfect.cli._settings import Action, GlobalFlag, HandlerContext, LogLevel, Setting
from pyfect.cli.cli_config import CliConfig
from pyfect.cli.cli_error import (
    CliError,
    ParseError,
    ShowHelp,
    UnrecognizedOption,
    UserError,
    get_user_message,
)
from pyfect.cli.cli_output import CurrentPresenter, Help, InvalidInvocation, resolve_formatter
from pyfect.cli.flag import Flag
from pyfect.cli.global_flag import Wizard
from pyfect.cli.param import FLAG, ParsedArgs
from pyfect.context import TagLike
from pyfect.effect import Effect, fail, gen, interrupt, provide_service
from pyfect.layer import Layer
from pyfect.layer import provide as layer_provide
from pyfect.logger import MinimumLogLevel
from pyfect.stdio import Stdio
from pyfect.terminal import QuitError

type AnyCommand = Command[Any, Any, Any, Any]


# --- providing services --------------------------------------------------------------


def _map_handle(
    command: AnyCommand,
    f: Callable[[Effect[None, Any, Any], Any], Effect[None, Any, Any]],
) -> Any:
    before = command.state.handle

    def handle(value: object, path: tuple[str, ...]) -> Effect[None, Any, Any]:
        own = value.context if isinstance(value, Selected) else value
        return f(before(value, path), own)

    return command._derive(handle=handle)  # pyright: ignore[reportPrivateUsage]


class _Provide[In, LA, LE, LR]:
    def __init__(self, f: Callable[[Effect[None, Any, Any], Any], Effect[None, Any, Any]]) -> None:
        self._f = f

    @overload
    def __call__[C, E = Never](
        self, command: Command[In, C, E, LA]
    ) -> Command[In, C, E | LE, LR]: ...
    @overload
    def __call__[C, E = Never, R = Never](
        self, command: Command[In, C, E, LA | R]
    ) -> Command[In, C, E | LE, R | LR]: ...
    def __call__(self, command: Command[Any, Any, Any, Any]) -> Command[Any, Any, Any, Any]:
        return _map_handle(command, self._f)


class _ProvideAny[LA, LE, LR]:
    """``_Provide`` for a service that doesn't read the config, so it fits a
    command of any config."""

    def __init__(self, f: Callable[[Effect[None, Any, Any], Any], Effect[None, Any, Any]]) -> None:
        self._f = f

    @overload
    def __call__[In, C, E = Never](
        self, command: Command[In, C, E, LA]
    ) -> Command[In, C, E | LE, LR]: ...
    @overload
    def __call__[In, C, E = Never, R = Never](
        self, command: Command[In, C, E, LA | R]
    ) -> Command[In, C, E | LE, R | LR]: ...
    def __call__(self, command: Command[Any, Any, Any, Any]) -> Command[Any, Any, Any, Any]:
        return _map_handle(command, self._f)


@overload
def provide[In, LA, LE = Never, LR = Never](
    layer: Callable[[In], Layer[LA, LE, LR]], *, local: bool = False
) -> _Provide[In, LA, LE, LR]: ...
@overload
def provide[LA, LE = Never, LR = Never](
    layer: Layer[LA, LE, LR], *, local: bool = False
) -> _ProvideAny[LA, LE, LR]: ...
def provide(
    layer: Layer[Any, Any, Any] | Callable[[Any], Layer[Any, Any, Any]], *, local: bool = False
) -> _Provide[Any, Any, Any, Any] | _ProvideAny[Any, Any, Any]:
    """Provides ``layer`` (or the layer built from the parsed config) to
    the handler: ``command.pipe(provide(database_layer))``."""

    def wrap(handler: Effect[None, Any, Any], value: Any) -> Effect[None, Any, Any]:
        built = layer(value) if callable(layer) else layer
        return handler.pipe(layer_provide(built, local=local))

    return _Provide(wrap) if callable(layer) else _ProvideAny(wrap)


@overload
def provide_sync[S, T, In](
    tag: TagLike[S, T], service: Callable[[In], S]
) -> _Provide[In, T, Never, Never]: ...
@overload
def provide_sync[S, T](tag: TagLike[S, T], service: S) -> _ProvideAny[T, Never, Never]: ...
def provide_sync(
    tag: TagLike[Any, Any], service: object
) -> _Provide[Any, Any, Never, Never] | _ProvideAny[Any, Never, Never]:
    """Provides ``service`` (or the one built from the parsed config) as
    ``tag``'s service to the handler."""

    def wrap(handler: Effect[None, Any, Any], value: Any) -> Effect[None, Any, Any]:
        built = service(value) if callable(service) else service
        return handler.pipe(provide_service(tag, built))

    return _Provide(wrap) if callable(service) else _ProvideAny(wrap)


@overload
def provide_effect[S, T, In, E2 = Never, R2 = Never](
    tag: TagLike[S, T], effect: Callable[[In], Effect[S, E2, R2]]
) -> _Provide[In, T, E2, R2]: ...
@overload
def provide_effect[S, T, E2 = Never, R2 = Never](
    tag: TagLike[S, T], effect: Effect[S, E2, R2]
) -> _ProvideAny[T, E2, R2]: ...
def provide_effect(
    tag: TagLike[Any, Any], effect: Effect[Any, Any, Any] | Callable[[Any], Effect[Any, Any, Any]]
) -> _Provide[Any, Any, Any, Any] | _ProvideAny[Any, Any, Any]:
    """Runs ``effect`` (or the one built from the parsed config) and
    provides its value as ``tag``'s service to the handler."""

    def wrap(handler: Effect[None, Any, Any], value: Any) -> Effect[None, Any, Any]:
        acquire = effect(value) if callable(effect) else effect
        return acquire.flat_map(lambda built: handler.pipe(provide_service(tag, built)))

    return _Provide(wrap) if callable(effect) else _ProvideAny(wrap)


def provide_effect_discard[In, C, EE, RR](
    command: Command[In, C, EE, RR],
    effect: Effect[object, EE, RR] | Callable[[In], Effect[object, EE, RR]],
) -> Command[In, C, EE, RR]:
    """Runs ``effect`` (or the one built from the parsed config) before the
    handler. Removes nothing, so it takes the command directly."""

    def wrap(handler: Effect[None, Any, Any], value: Any) -> Effect[None, Any, Any]:
        before = effect(value) if callable(effect) else effect
        return before.and_then(handler)

    return _map_handle(command, wrap)


class _WithGlobalFlags[T]:
    def __init__(self, flags: tuple[GlobalFlag, ...]) -> None:
        self._flags = flags

    @overload
    def __call__[In, C, E = Never](self, command: Command[In, C, E, T]) -> Command[In, C, E]: ...
    @overload
    def __call__[In, C, E = Never, R = Never](
        self, command: Command[In, C, E, T | R]
    ) -> Command[In, C, E, R]: ...
    def __call__(self, command: Command[Any, Any, Any, Any]) -> Command[Any, Any, Any, Any]:
        merged = tuple(dict.fromkeys((*command.state.global_flags, *self._flags)))
        return command._derive(global_flags=merged)  # pyright: ignore[reportPrivateUsage]


def with_global_flags[T = Never](*flags: TagLike[Any, T] | Action[Any]) -> _WithGlobalFlags[T]:
    """Global flags for the command and its subcommands: ``Setting``
    classes, provided to the handlers (and removed from ``R``), and
    ``Action``s. ``cmd.pipe(with_global_flags(Region, Verbose))``."""
    for flag in flags:
        if not isinstance(flag, Action) and not (
            isinstance(flag, type) and issubclass(flag, Setting)
        ):
            raise TypeError(f"{flag!r} is neither a Setting class nor an Action")
    return _WithGlobalFlags(cast("tuple[GlobalFlag, ...]", flags))


# --- running -------------------------------------------------------------------------


def _out_of_scope(
    every: Sequence[GlobalFlag],
    active: Sequence[GlobalFlag],
    flag_map: dict[str, list[str]],
    path: tuple[str, ...],
) -> list[UnrecognizedOption]:
    errors: list[UnrecognizedOption] = []
    seen: set[str] = set()
    for global_flag in every:
        if global_flag in active:
            continue
        for single in flag_of(global_flag).param.singles():
            option = f"--{single.name}"
            if not flag_map.get(single.name) or option in seen:
                continue
            seen.add(option)
            errors.append(UnrecognizedOption(option, (), path))
    return errors


def _show_help(command: AnyCommand, error: ShowHelp, render_errors: bool) -> Effect[None]:
    def body():
        settings = yield from CliConfig()
        presenter = yield from CurrentPresenter()
        path = error.command_path
        doc = help_for_path(command, path, settings.built_ins)
        event = (
            InvalidInvocation(path, doc, error.errors)
            if render_errors and error.errors
            else Help("Implicit", path, doc)
        )
        yield from presenter.present(event)

    return gen(body)


def _show_user_error(error: object, message: str) -> Effect[None]:
    def body():
        formatter = yield from resolve_formatter()
        rendered = error if isinstance(error, UserError) else UserError(error, message)
        yield from console.error(formatter.format_error(rendered))
        object.__setattr__(error, "error_reported", False)

    return gen(body)


class _Runner:
    """One run of a command line: global flags, then the command's parse,
    then the handler with the settings provided."""

    def __init__(self, command: AnyCommand, version: str, render_errors: bool) -> None:
        self.command = command
        self.version = version
        self.render_errors = render_errors

    def _wizard(self, args: Sequence[str], path: tuple[str, ...]) -> Effect[None, Any, Any]:
        command = self.command

        def body():
            theme = yield from prompt.PromptTheme()
            colors = theme.colors
            intro = wizard_.render_introduction(
                command.name, self.version, command.description, colors
            )
            yield from console.log(intro)
            prefix = (
                command.name,
                *(arg for arg in args if arg != "--wizard" and not arg.startswith("--wizard=")),
            )
            result = yield from wizard_.run(command, command_path=path, prefix=prefix)
            yield from console.log(wizard_.render_completion(result.display_args, colors))
            should_run = yield from prompt.run(
                prompt.toggle("Run this command?", initial=True, active="yes", inactive="no")
            )
            if should_run:
                yield from console.log()
                yield from _Runner(command, self.version, False).run(result.args[1:])

        def quit(error: object) -> Effect[None, Any, Any]:
            if isinstance(error, QuitError):
                return prompt.PromptTheme().flat_map(
                    lambda theme: console.log(wizard_.render_quit(theme.colors))
                )
            return fail(error)

        return gen(body).catch_all(quit)

    def _body(self, args: Sequence[str]) -> Generator[Effect[Any, Any, Any], Any]:
        command = self.command
        settings = yield from CliConfig()
        built_ins = settings.built_ins
        lexed = lex(args)
        every = global_flags_for_tree(command, built_ins)
        params = [s for g in every for s in flag_of(g).param.singles() if s.kind == FLAG]
        taken = consume_global_flags(lexed.tokens, command, create_flag_registry(params))
        empty = ParsedArgs({name: tuple(values) for name, values in taken.flag_map.items()}, ())
        parsed = parse_args(LexResult(taken.remainder, lexed.trailing_operands), command)
        path = (command.name, *get_command_path(parsed))

        def to_show_help(error: CliError) -> CliError:
            return (
                error
                if isinstance(error, ShowHelp)
                else ShowHelp(path, (cast("ParseError", error),))
            )

        active = global_flags_for_path(command, path, built_ins)
        out_of_scope = _out_of_scope(every, active, taken.flag_map, path)
        if out_of_scope or taken.errors:
            errors: tuple[ParseError, ...] = (*taken.errors, *out_of_scope, *parsed.errors)
            return (yield from fail(ShowHelp(path, errors)))
        context = HandlerContext(command, path, self.version, built_ins)
        for action in (flag for flag in active if isinstance(flag, Action)):
            flag: Flag[Any] = action.flag
            if not any(taken.flag_map.get(s.name) for s in flag.param.singles()):
                continue
            parsed_flag = yield from flag.parse(empty).map_error(to_show_help)
            if action is Wizard:
                return (yield from self._wizard(args, path))
            return (yield from action.run(parsed_flag[1], context))
        if parsed.errors:
            return (yield from fail(ShowHelp(path, parsed.errors)))
        value = yield from command.state.parse(command, parsed).map_error(to_show_help)
        program = command.state.handle(value, (command.name,))
        level = None
        if LogLevel in active:
            _, level = yield from LogLevel.flag.parse(empty).map_error(to_show_help)
        program = program.pipe(provide_service(LogLevel, level))
        for global_flag in active:
            if isinstance(global_flag, Action) or global_flag is LogLevel:
                continue
            _, setting = yield from global_flag.flag.parse(empty).map_error(to_show_help)
            program = program.pipe(provide_service(global_flag, setting))
        if level is not None:
            program = program.pipe(provide_service(MinimumLogLevel, level))
        return (yield from program)

    def _on_error(self, error: object) -> Effect[None, Any, Any]:
        if isinstance(error, ShowHelp):
            return _show_help(self.command, error, self.render_errors).and_then(fail(error))
        message = get_user_message(error)
        if self.render_errors and message is not None:
            return _show_user_error(error, message).and_then(fail(error))
        if isinstance(error, QuitError):
            return interrupt()
        return fail(error)

    def run(self, args: Sequence[str]) -> Effect[None, Any, Any]:
        return gen(lambda: self._body(args)).catch_all(self._on_error)


def run_with[In, C, E, R](
    command: Command[In, C, E, R], *, version: str, render_errors: bool = True
) -> Callable[[Sequence[str]], Effect[None, E | CliError, R | Environment]]:
    """Runs the command on the given arguments (without the program name).
    Help and parse errors are shown and fail with ``ShowHelp``; an error with
    a user message is printed (unless ``render_errors`` is off); a
    ``QuitError`` from a prompt interrupts."""
    runner = _Runner(command, version, render_errors)
    return runner.run


def run[In, C, E, R](
    command: Command[In, C, E, R], *, version: str, render_errors: bool = True
) -> Effect[None, E | CliError, R | Environment]:
    """``run_with`` on the process's arguments, read from ``Stdio``."""
    runner = run_with(command, version=version, render_errors=render_errors)

    def body():
        stdio = yield from Stdio()
        args = yield from stdio.args
        return (yield from runner(args))

    return gen(body)


def wizard[In, C, E, R](
    command: Command[In, C, E, R], *, prefix: Sequence[str] | None = None
) -> Effect[tuple[str, ...], CliError | QuitError, Environment]:
    """Asks for the command's flags, arguments and subcommands; gives the
    command line (with the program name)."""
    return wizard_.run(command, prefix=None if prefix is None else tuple(prefix)).map(
        lambda result: result.args
    )


def show_help(command: AnyCommand, path: Sequence[str] | None = None) -> Effect[None]:
    """Presents the help of ``path`` (default: the command itself)."""
    return _show_help(command, ShowHelp(tuple(path or (command.name,))), True)


__all__ = [
    "AnyCommand",
    "CliError",
    "Command",
    "CommandContext",
    "Config",
    "Example",
    "ParsedTokens",
    "QuitError",
    "SubcommandGroup",
    "group",
    "make",
    "provide",
    "provide_effect",
    "provide_effect_discard",
    "provide_sync",
    "run",
    "run_with",
    "show_help",
    "with_global_flags",
    "wizard",
]
