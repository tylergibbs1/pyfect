"""The errors a command line can fail with (Effect's ``CliError``).

Parsing collects ``UnrecognizedOption``, ``MissingOption``,
``InvalidValue`` and the rest; ``Command.run`` shows them with the help in
a ``ShowHelp``. A handler fails with ``UserError`` (or any error with a
``__cli_user_message__``) to have the runner print a message for the user
instead of a stack trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal, Protocol, runtime_checkable

from pyfect._json_text import stringify
from pyfect.errors import TaggedError


@runtime_checkable
class HasUserMessage(Protocol):
    """An error the CLI runner reports with this text (Effect's
    ``CliError.userMessage`` symbol)."""

    @property
    def __cli_user_message__(self) -> str: ...


def get_user_message(error: object) -> str | None:
    """The error's ``__cli_user_message__``, if it has a string one."""
    message = getattr(error, "__cli_user_message__", None)
    return message if isinstance(message, str) else None


def _suggestion_text(suggestions: tuple[str, ...]) -> str:
    if not suggestions:
        return ""
    return "\n\n  Did you mean this?\n    " + "\n    ".join(suggestions)


class CliError(TaggedError):
    """Every CLI error; each class's ``tag`` is Effect's ``_tag``."""

    @property
    def message(self) -> str:
        raise NotImplementedError

    @property
    def tag_name(self) -> str:
        """Effect's ``_tag``: the class's ``tag``."""
        return getattr(self, "tag", type(self).__name__)


@dataclass(eq=False)
class UnrecognizedOption(CliError):
    option: str
    suggestions: tuple[str, ...] = ()
    command: tuple[str, ...] | None = None
    tag: ClassVar[Literal["UnrecognizedOption"]] = "UnrecognizedOption"

    @property
    def message(self) -> str:
        base = (
            f"Unrecognized flag: {self.option} in command {' '.join(self.command)}"
            if self.command
            else f"Unrecognized flag: {self.option}"
        )
        return base + _suggestion_text(self.suggestions)


@dataclass(eq=False)
class DuplicateOption(CliError):
    option: str
    parent_command: str
    child_command: str
    tag: ClassVar[Literal["DuplicateOption"]] = "DuplicateOption"

    @property
    def message(self) -> str:
        return (
            f'Duplicate flag name "{self.option}" in parent command "{self.parent_command}" '
            f'and subcommand "{self.child_command}". '
            "Parent will always claim this flag (Mode A semantics). "
            "Consider renaming one of them to avoid confusion."
        )


@dataclass(eq=False)
class MissingOption(CliError):
    option: str
    tag: ClassVar[Literal["MissingOption"]] = "MissingOption"

    @property
    def message(self) -> str:
        return f"Missing required flag: --{self.option}"


@dataclass(eq=False)
class MissingArgument(CliError):
    argument: str
    tag: ClassVar[Literal["MissingArgument"]] = "MissingArgument"

    @property
    def message(self) -> str:
        return f"Missing required argument: {self.argument}"


@dataclass(eq=False)
class UnexpectedArgument(CliError):
    arguments: tuple[str, ...]
    tag: ClassVar[Literal["UnexpectedArgument"]] = "UnexpectedArgument"

    @property
    def message(self) -> str:
        label = "argument" if len(self.arguments) == 1 else "arguments"
        return f"Unexpected positional {label}: {', '.join(stringify(a) for a in self.arguments)}"


@dataclass(eq=False)
class InvalidValue(CliError):
    option: str
    value: str
    expected: str
    kind: Literal["flag", "argument"]
    tag: ClassVar[Literal["InvalidValue"]] = "InvalidValue"

    @property
    def message(self) -> str:
        expectation = (
            self.expected
            if self.expected.startswith(("Expected ", "Expected:"))
            else f"Expected: {self.expected}"
        )
        if self.kind == "argument":
            return f'Invalid value for argument <{self.option}>: "{self.value}". {expectation}'
        if not self.value:
            return f"Missing value for flag --{self.option}. {expectation}"
        return f'Invalid value for flag --{self.option}: "{self.value}". {expectation}'


@dataclass(eq=False)
class UnknownSubcommand(CliError):
    subcommand: str
    suggestions: tuple[str, ...] = ()
    parent: tuple[str, ...] | None = None
    tag: ClassVar[Literal["UnknownSubcommand"]] = "UnknownSubcommand"

    @property
    def message(self) -> str:
        base = (
            f'Unknown subcommand "{self.subcommand}" for "{" ".join(self.parent)}"'
            if self.parent
            else f'Unknown subcommand "{self.subcommand}"'
        )
        return base + _suggestion_text(self.suggestions)


@dataclass(eq=False)
class ValidationError(CliError):
    detail: str
    tag: ClassVar[Literal["ValidationError"]] = "ValidationError"

    @property
    def message(self) -> str:
        return self.detail


@dataclass(eq=False)
class UserError(CliError):
    """A handler's failure with a message for the user: ``user_message``,
    else a non-empty string ``cause``, else the cause exception's message,
    else ``"An error occurred"``. ``run_main`` still reports it."""

    cause: object
    user_message: str | None = None
    tag: ClassVar[Literal["UserError"]] = "UserError"

    @property
    def message(self) -> str:
        if self.user_message:
            return self.user_message
        if isinstance(self.cause, str) and self.cause:
            return self.cause
        if isinstance(self.cause, BaseException) and str(self.cause):
            return str(self.cause)
        return "An error occurred"

    @property
    def __cli_user_message__(self) -> str:
        return self.message


type ParseError = (
    UnrecognizedOption
    | DuplicateOption
    | MissingOption
    | MissingArgument
    | UnexpectedArgument
    | InvalidValue
    | UnknownSubcommand
    | ValidationError
    | UserError
)
"""Every CLI error but ``ShowHelp`` (Effect's ``NonShowHelpErrors``)."""


@dataclass(eq=False)
class ShowHelp(CliError):
    """Show the help of ``command_path``, with ``errors`` when parsing
    failed. Exits with 1 when there are errors, else 0; never reported by
    ``run_main``."""

    command_path: tuple[str, ...]
    errors: tuple[ParseError, ...] = field(default=())
    tag: ClassVar[Literal["ShowHelp"]] = "ShowHelp"
    error_reported: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # ``exit_code`` is per class on ``TaggedError``; this one depends on
        # the errors, as Effect's ``errorExitCode`` does.
        object.__setattr__(self, "exit_code", 1 if self.errors else 0)

    @property
    def message(self) -> str:
        return "Help requested"


__all__ = [
    "CliError",
    "DuplicateOption",
    "HasUserMessage",
    "InvalidValue",
    "MissingArgument",
    "MissingOption",
    "ParseError",
    "ShowHelp",
    "UnexpectedArgument",
    "UnknownSubcommand",
    "UnrecognizedOption",
    "UserError",
    "ValidationError",
    "get_user_message",
]
