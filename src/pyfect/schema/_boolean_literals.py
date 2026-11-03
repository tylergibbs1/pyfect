"""The texts of booleans (Effect's ``TrueLiterals``, ``FalseLiterals`` and
``BooleanLiterals``, as config and URL parameters read them)."""

from __future__ import annotations

from typing import Literal

from pyfect.schema import transformation as T
from pyfect.schema._literals import Literals, LiteralsSchema
from pyfect.schema._primitives import Boolean
from pyfect.schema._transform import DecodeToSchema, decode_to

type TrueLiteral = Literal["true", "yes", "on", "1", "y"]
type FalseLiteral = Literal["false", "no", "off", "0", "n"]

TrueLiterals: LiteralsSchema[TrueLiteral] = Literals("true", "yes", "on", "1", "y")
FalseLiterals: LiteralsSchema[FalseLiteral] = Literals("false", "no", "off", "0", "n")


def _is_true(text: TrueLiteral | FalseLiteral) -> bool:
    return text in TrueLiterals.literals


def _text(value: bool) -> TrueLiteral | FalseLiteral:
    return "true" if value else "false"


BooleanLiterals: DecodeToSchema[bool, str] = Literals(
    *TrueLiterals.literals, *FalseLiterals.literals
).pipe(decode_to(Boolean, T.transform(decode=_is_true, encode=_text)))
"""A ``bool`` read from one of those texts, written as ``"true"`` / ``"false"``."""
