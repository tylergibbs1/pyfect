"""Generated source for one schema (Effect's ``Code`` / ``makeCode``)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Code:
    """The ``runtime`` expression building a schema and the ``type`` of
    its values."""

    runtime: str
    type: str


def make_code(runtime: str, type: str, /) -> Code:
    """``Code(runtime, type)`` (Effect's ``makeCode``)."""
    return Code(runtime, type)
