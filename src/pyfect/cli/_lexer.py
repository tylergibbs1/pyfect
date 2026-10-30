"""Turns raw arguments into the tokens the parser reads (Effect's internal
``cli/internal/lexer``): long options (``--name``, ``--name=value``), short
options and clusters (``-x``, ``-abc``, ``-n=3``) and values.

Everything after ``--`` is kept as trailing operands, so values that look
like options survive exactly. A lone ``-`` and negative numbers (``-3``,
``-3.70``) are values."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LongOption:
    name: str
    raw: str
    value: str | None = None


@dataclass(frozen=True, slots=True)
class ShortOption:
    flag: str
    raw: str
    value: str | None = None


@dataclass(frozen=True, slots=True)
class Value:
    value: str


type FlagToken = LongOption | ShortOption
type Token = LongOption | ShortOption | Value


@dataclass(frozen=True, slots=True)
class LexResult:
    tokens: tuple[Token, ...]
    trailing_operands: tuple[str, ...]


_NEGATIVE_NUMBER = re.compile(r"-(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def lex(argv: Sequence[str]) -> LexResult:
    try:
        end = list(argv).index("--")
    except ValueError:
        return LexResult(_lex_tokens(argv), ())
    return LexResult(_lex_tokens(argv[:end]), tuple(argv[end + 1 :]))


def _lex_tokens(args: Sequence[str]) -> tuple[Token, ...]:
    tokens: list[Token] = []
    for arg in args:
        if not arg.startswith("-") or _NEGATIVE_NUMBER.fullmatch(arg):
            tokens.append(Value(arg))
        elif arg.startswith("--"):
            name, equals, value = arg[2:].partition("=")
            if not equals:
                tokens.append(LongOption(name, arg))
            elif name == "":
                tokens.append(Value(arg))
            else:
                tokens.append(LongOption(name, arg, value))
        elif len(arg) > 1:
            flags = arg[1:]
            cluster, equals, value = flags.partition("=")
            if equals:
                chars = list(cluster)
                last = chars.pop() if chars else ""
                tokens.extend(ShortOption(ch, f"-{ch}") for ch in chars)
                tokens.append(ShortOption(last, f"-{last}", value))
            else:
                tokens.extend(ShortOption(ch, f"-{ch}") for ch in flags)
        else:
            tokens.append(Value(arg))
    return tuple(tokens)
