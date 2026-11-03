"""Transformations between a value and its text, read by a parser giving a
``Result`` whose error has a ``message`` (``NetAddressError``,
``SemVerError``): a rejected text is an ``InvalidValue`` with that message."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.result import Ok, Result
from pyfect.schema import transformation as T
from pyfect.schema._options import ParseOptions
from pyfect.schema.issue import InvalidValue, Issue, reported


class HasMessage(Protocol):
    @property
    def message(self) -> str: ...


def parsed_text[A](
    parse: Callable[[str], Result[A, HasMessage]], format: Callable[[A], str]
) -> T.Transformation[A, str]:
    """``parse`` decodes, ``format`` encodes."""

    def decode(text: str, options: ParseOptions) -> Exit[A, Issue]:
        result = parse(text)
        if isinstance(result, Ok):
            return Success(result.value)
        return fail_exit(InvalidValue({"message": result.error.message}, reported(text, options)))

    def encode(value: A, _: ParseOptions) -> Exit[str, Issue]:
        return Success(format(value))

    return T.transform_effect(decode=decode, encode=encode)
