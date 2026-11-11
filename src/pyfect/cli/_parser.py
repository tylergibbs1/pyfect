"""Splits lexed tokens across a command tree (Effect's internal
``cli/internal/parser``): each level's flags and arguments, the chosen
subcommand, and the errors (unknown flags and subcommands, missing
values) collected rather than raised, so help can show them all.

A command's own flags stay at its level; its shared flags may also follow
a subcommand's name (npm style). Global flags are taken out first by
``consume_global_flags``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pyfect.cli import primitive as primitive_
from pyfect.cli._command import Command, ParsedTokens, SelectedTokens
from pyfect.cli._lexer import FlagToken, LexResult, LongOption, ShortOption, Token, Value
from pyfect.cli._suggest import suggest
from pyfect.cli.cli_error import InvalidValue, ParseError, UnknownSubcommand, UnrecognizedOption
from pyfect.cli.param import FLAG, Single

type AnyCommand = Command[Any, Any, Any, Any]
type FlagMap = dict[str, list[str]]


def get_command_path(parsed: ParsedTokens) -> tuple[str, ...]:
    path: list[str] = []
    current = parsed.subcommand
    while current is not None:
        path.append(current.name)
        current = current.parsed_input.subcommand
    return tuple(path)


# --- registry ----------------------------------------------------------------------


def negated_name(param: Single[Any]) -> str | None:
    if not primitive_.is_boolean(param.primitive) or param.negation is False:
        return None
    return param.negation if param.negation is not None else f"no-{param.name}"


@dataclass(frozen=True, slots=True)
class FlagRegistry:
    params: tuple[Single[Any], ...]
    index: dict[str, Single[Any]]
    negations: dict[str, Single[Any]]


def create_flag_registry(params: Sequence[Single[Any]]) -> FlagRegistry:
    """The flags by name, alias and negation. A clash is a definition
    error, raised as ``ValueError``."""
    index: dict[str, Single[Any]] = {}
    negations: dict[str, Single[Any]] = {}
    for param in params:
        if param.name in index:
            raise ValueError(f'Duplicate flag name "{param.name}" in command definition')
        index[param.name] = param
        for alias in param.aliases:
            if alias in index:
                raise ValueError(
                    f'Duplicate flag/alias "{alias}" in command definition '
                    f'(conflicts with "{index[alias].name}")'
                )
            index[alias] = param
        negation = negated_name(param)
        if negation is not None:
            if negation in negations:
                raise ValueError(
                    f'Duplicate negation "{negation}" in command definition '
                    f'(conflicts with "{negations[negation].name}")'
                )
            negations[negation] = param
    return FlagRegistry(tuple(params), index, negations)


def _flag_singles(params: Sequence[Any]) -> tuple[Single[Any], ...]:
    return tuple(s for param in params for s in param.singles() if s.kind == FLAG)


def _local_flags(command: AnyCommand) -> tuple[Single[Any], ...]:
    return _flag_singles(command.state.config.flags)


def _context_flags(command: AnyCommand) -> tuple[Single[Any], ...]:
    return _flag_singles(command.state.context_config.flags)


def _subcommand_index(command: AnyCommand) -> dict[str, AnyCommand]:
    index: dict[str, AnyCommand] = {}

    def set_key(key: str, sub: AnyCommand) -> None:
        existing = index.get(key)
        if existing is not None and existing is not sub:
            raise ValueError(
                f'Duplicate subcommand name/alias "{key}" in command definition '
                f'(conflicts with "{existing.name}")'
            )
        index[key] = sub

    for group in command.subcommands:
        for sub in group.commands:
            set_key(sub.name, sub)
            if sub.alias and sub.alias != sub.name:
                set_key(sub.alias, sub)
    return index


def empty_flag_map(params: Sequence[Single[Any]]) -> FlagMap:
    return {param.name: [] for param in params}


# --- reading a flag's value ------------------------------------------------------------


class _Cursor:
    def __init__(self, tokens: Sequence[Token]) -> None:
        self._tokens = tokens
        self._index = 0

    def peek(self) -> Token | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def take(self) -> Token | None:
        token = self.peek()
        if token is not None:
            self._index += 1
        return token

    def rest(self) -> tuple[Token, ...]:
        return tuple(self._tokens[self._index :])


@dataclass(frozen=True, slots=True)
class _Resolved:
    param: Single[Any]
    negated: bool


@dataclass(frozen=True, slots=True)
class _Consumed:
    """A flag's value (``None`` adds nothing) or the error reading it, and
    the tokens taken for it."""

    value: str | None
    error: InvalidValue | None
    tokens: tuple[Token, ...]


def _token_name(token: FlagToken) -> str:
    return token.name if isinstance(token, LongOption) else token.flag


def _resolve(token: FlagToken, registry: FlagRegistry) -> _Resolved | None:
    name = _token_name(token)
    direct = registry.index.get(name)
    if direct is not None and direct.name == name:
        return _Resolved(direct, False)
    negated = registry.negations.get(token.name) if isinstance(token, LongOption) else None
    if negated is not None:
        return _Resolved(negated, True)
    if direct is not None:
        return _Resolved(direct, False)
    return None


def _resolve_any(token: FlagToken, registries: Sequence[FlagRegistry]) -> _Resolved | None:
    for registry in registries:
        resolved = _resolve(token, registry)
        if resolved is not None:
            return resolved
    return None


def _invalid_negated(token: FlagToken, spec: Single[Any], value: str) -> InvalidValue:
    return InvalidValue(
        spec.name,
        value,
        f"omit the value and use {token.raw} by itself to set --{spec.name} to false",
        "flag",
    )


def _missing_value(spec: Single[Any]) -> InvalidValue:
    choices = spec.primitive.choice_keys
    expected = (
        (spec.type_name or primitive_.type_name(spec.primitive))
        if choices is None
        else " | ".join(choices)
    )
    return InvalidValue(spec.name, "", expected, "flag")


def _boolean_literal(token: Token | None) -> str | None:
    if isinstance(token, Value) and (
        primitive_.is_true_literal(token.value) or primitive_.is_false_literal(token.value)
    ):
        return token.value
    return None


def _taken(token: Token | None) -> tuple[Token, ...]:
    return () if token is None else (token,)


def _consume(cursor: _Cursor, token: FlagToken, resolved: _Resolved) -> _Consumed:  # noqa: PLR0911 - one return per case
    spec = resolved.param
    if resolved.negated:
        if token.value is not None:
            return _Consumed(None, _invalid_negated(token, spec, token.value), ())
        literal = _boolean_literal(cursor.peek()) if spec.optional_value is None else None
        if literal is not None:
            return _Consumed(None, _invalid_negated(token, spec, literal), _taken(cursor.take()))
        return _Consumed("false", None, ())
    if token.value is not None:
        return _Consumed(token.value, None, ())
    if spec.optional_value is not None:
        return _Consumed(spec.optional_value, None, ())
    if primitive_.is_boolean(spec.primitive):
        literal = _boolean_literal(cursor.peek())
        taken = _taken(cursor.take()) if literal is not None else ()
        return _Consumed(literal or "true", None, taken)
    following = cursor.peek()
    if isinstance(following, Value):
        return _Consumed(following.value, None, _taken(cursor.take()))
    return _Consumed(None, _missing_value(spec), ())


@dataclass(frozen=True, slots=True)
class FlagsTaken:
    flag_map: FlagMap
    remainder: tuple[Token, ...]
    errors: tuple[InvalidValue, ...]


def consume_known_flags(tokens: Sequence[Token], registry: FlagRegistry) -> FlagsTaken:
    """Takes the registry's flags (and their values) out of ``tokens``."""
    flag_map = empty_flag_map(registry.params)
    remainder: list[Token] = []
    errors: list[InvalidValue] = []
    cursor = _Cursor(tokens)
    while (token := cursor.take()) is not None:
        resolved = None if isinstance(token, Value) else _resolve(token, registry)
        if isinstance(token, Value) or resolved is None:
            remainder.append(token)
            continue
        consumed = _consume(cursor, token, resolved)
        if consumed.error is not None:
            errors.append(consumed.error)
        elif consumed.value is not None:
            flag_map[resolved.param.name].append(consumed.value)
    return FlagsTaken(flag_map, tuple(remainder), tuple(errors))


# --- global flags ------------------------------------------------------------------


def _local_precedes_subcommand(
    token: FlagToken,
    rest: Sequence[Token],
    resolved: _Resolved,
    sub_index: dict[str, AnyCommand],
    registries: Sequence[FlagRegistry],
) -> bool:
    cursor = _Cursor(rest)
    _consume(cursor, token, resolved)
    while (following := cursor.take()) is not None:
        if isinstance(following, Value):
            return following.value in sub_index
        known = _resolve_any(following, registries)
        if known is not None:
            _consume(cursor, following, known)
    return False


def consume_global_flags(
    tokens: Sequence[Token], command: AnyCommand, registry: FlagRegistry
) -> FlagsTaken:
    """Takes the global flags out of ``tokens``, level by level: a token a
    command's own or shared flag claims stays (with its value), unless a
    local flag of the same name only precedes a subcommand."""
    flag_map = empty_flag_map(registry.params)
    errors: list[InvalidValue] = []

    def level(
        tokens: Sequence[Token], command: AnyCommand, ignored: tuple[FlagRegistry, ...]
    ) -> list[Token]:
        local = create_flag_registry(_local_flags(command))
        inherited = create_flag_registry(_context_flags(command))
        sub_index = _subcommand_index(command)
        cursor = _Cursor(tokens)
        remainder: list[Token] = []
        awaiting_first_value = True

        def preserve(token: FlagToken, resolved: _Resolved) -> None:
            remainder.append(token)
            remainder.extend(_consume(cursor, token, resolved).tokens)

        while (token := cursor.take()) is not None:
            if isinstance(token, Value):
                if awaiting_first_value:
                    sub = sub_index.get(token.value)
                    if sub is not None:
                        remainder.append(token)
                        remainder.extend(level(cursor.rest(), sub, (*ignored, inherited)))
                        return remainder
                    awaiting_first_value = False
                remainder.append(token)
                continue
            claimed = _resolve_any(token, ignored) or _resolve(token, inherited)
            if claimed is not None:
                preserve(token, claimed)
                continue
            own = _resolve(token, local)
            global_ = _resolve(token, registry)
            if own is not None and (
                global_ is None
                or not awaiting_first_value
                or not _local_precedes_subcommand(
                    token, cursor.rest(), own, sub_index, (local, inherited, registry)
                )
            ):
                preserve(token, own)
                continue
            if global_ is not None:
                consumed = _consume(cursor, token, global_)
                if consumed.error is not None:
                    errors.append(consumed.error)
                elif consumed.value is not None:
                    flag_map[global_.param.name].append(consumed.value)
                continue
            remainder.append(token)
        return remainder

    remainder = level(tokens, command, ())
    return FlagsTaken(flag_map, tuple(remainder), tuple(errors))


# --- one command level -------------------------------------------------------------


def _unrecognized(
    token: FlagToken, params: Sequence[Single[Any]], path: tuple[str, ...]
) -> UnrecognizedOption:
    printable = f"--{token.name}" if isinstance(token, LongOption) else f"-{token.flag}"
    valid: list[str] = []
    for param in params:
        if param.hidden:
            continue
        valid.append(param.name)
        negation = negated_name(param)
        if negation is not None:
            valid.append(negation)
        valid.extend(param.aliases)
    suggestions = tuple(
        f"-{name}" if len(name) == 1 else f"--{name}" for name in suggest(_token_name(token), valid)
    )
    return UnrecognizedOption(printable, suggestions, path)


@dataclass(frozen=True, slots=True)
class _Level:
    flags: FlagMap
    arguments: tuple[str, ...]
    errors: tuple[ParseError, ...]
    sub: AnyCommand | None = None
    child_tokens: tuple[Token, ...] = ()


class _LevelScan:
    """Scans one command level: flags into the map, the first value either
    a subcommand (ending the level) or the first argument."""

    def __init__(self, command: AnyCommand, path: tuple[str, ...]) -> None:
        local = _local_flags(command)
        inherited = _context_flags(command)
        inherited_names = {param.name for param in inherited}
        self.command = command
        self.path = path
        self.registry = create_flag_registry(local)
        self.inherited = create_flag_registry(inherited)
        self.local_names = tuple(p.name for p in local if p.name not in inherited_names)
        self.flags = empty_flag_map(local)
        self.arguments: list[str] = []
        self.errors: list[ParseError] = []
        self.awaiting_first_value = True

    def _flag(self, token: FlagToken, cursor: _Cursor) -> None:
        resolved = _resolve(token, self.registry)
        if resolved is None:
            self.errors.append(_unrecognized(token, self.registry.params, self.path))
            return
        consumed = _consume(cursor, token, resolved)
        if consumed.error is not None:
            self.errors.append(consumed.error)
        elif consumed.value is not None:
            self.flags[resolved.param.name].append(consumed.value)

    def _subcommand(self, sub: AnyCommand, cursor: _Cursor) -> _Level:
        selected = (*self.path, sub.name)
        for name in self.local_names:
            if self.flags.get(name):
                self.errors.append(UnrecognizedOption(f"--{name}", (), selected))
        tail = consume_known_flags(cursor.rest(), self.inherited)
        for name, values in tail.flag_map.items():
            self.flags[name].extend(values)
        self.errors.extend(tail.errors)
        return _Level(self.flags, (), tuple(self.errors), sub, tail.remainder)

    def _unknown_subcommand(self, value: str, index: dict[str, AnyCommand]) -> None:
        if self.command.state.config.arguments or not index:
            return
        visible = [key for key, sub in index.items() if not sub.unlisted]
        self.errors.append(UnknownSubcommand(value, suggest(value, visible), self.path))

    def scan(self, tokens: Sequence[Token]) -> _Level:
        cursor = _Cursor(tokens)
        while (token := cursor.take()) is not None:
            if isinstance(token, (LongOption, ShortOption)):
                self._flag(token, cursor)
                continue
            if self.awaiting_first_value:
                index = _subcommand_index(self.command)
                sub = index.get(token.value)
                if sub is not None:
                    return self._subcommand(sub, cursor)
                self._unknown_subcommand(token.value, index)
                self.awaiting_first_value = False
            self.arguments.append(token.value)
        return _Level(self.flags, tuple(self.arguments), tuple(self.errors))


def parse_args(lexed: LexResult, command: AnyCommand, path: tuple[str, ...] = ()) -> ParsedTokens:
    """The command line split across ``command``'s tree."""
    new_path = (*path, command.name)
    result = _LevelScan(command, new_path).scan(lexed.tokens)
    flags = {name: tuple(values) for name, values in result.flags.items()}
    if result.sub is None:
        return ParsedTokens(
            flags, (*result.arguments, *lexed.trailing_operands), None, result.errors
        )
    sub_parsed = parse_args(
        LexResult(result.child_tokens, lexed.trailing_operands), result.sub, new_path
    )
    return ParsedTokens(
        flags,
        (),
        SelectedTokens(result.sub.name, sub_parsed),
        (*result.errors, *sub_parsed.errors),
    )


__all__ = [
    "FlagRegistry",
    "consume_global_flags",
    "consume_known_flags",
    "create_flag_registry",
    "empty_flag_map",
    "get_command_path",
    "negated_name",
    "parse_args",
]
