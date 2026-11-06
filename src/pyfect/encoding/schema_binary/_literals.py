"""A literal's text as JavaScript's ``String(literal)`` writes it, which is
what SchemaBinary hashes."""

from __future__ import annotations

from pyfect._js import js_number


def literal_text(literal: object) -> str:
    match literal:
        case str():
            return literal
        case None:
            return "null"
        case bool():
            return "true" if literal else "false"
        case int() | float():
            return js_number(literal)
        case _:
            return str(literal)


def literal_kind_code(literal: object) -> int:
    """Effect's ``typeof`` of a sentinel literal: its hash input."""
    match literal:
        case str():
            return 1
        case bool():
            return 3
        case int() | float():
            return 2
        case _:
            return 5


def literal_key(literal: object) -> object:
    """A dictionary key equal for a literal and any value that is that
    literal: ``1`` and ``1.0`` are one number, ``True`` is not ``1``."""
    match literal:
        case bool():
            return ("boolean", literal)
        case int() | float():
            return ("number", float(literal))
        case str() | None:
            return literal
        case _:
            return None
