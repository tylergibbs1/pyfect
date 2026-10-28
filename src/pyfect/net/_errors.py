"""The error of the address parsers and constructors (Effect's
``NetAddressError``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Never

from pyfect.errors import TaggedError
from pyfect.result import Err


@dataclass(eq=False)
class NetAddressError(TaggedError, ValueError):
    """An address, host, network or record was rejected. ``input`` is the
    value the failing step rejected (a part of the text, or the address a
    port was given with)."""

    message: str
    input: object
    cause: object = None


def address_error(input: object, message: str) -> Err[NetAddressError]:
    return Err(NetAddressError(message, input))


def raise_error(input: object, message: str) -> Never:
    raise NetAddressError(message, input)
