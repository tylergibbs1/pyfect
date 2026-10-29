"""Ids for tool calls and response parts (Effect's ``IdGenerator``).

The default makes ``id_`` and 16 random characters; ``layer`` provides one
of another alphabet, prefix, separator or size. Ids draw from ``Random``,
so a seeded ``Random`` makes them reproducible.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

import pyfect as fx
from pyfect import layer as L
from pyfect import random as Random
from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.errors import IllegalArgumentError

DEFAULT_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


@dataclass(frozen=True)
class Service:
    generate_id: Callable[[], Effect[str]]


class IdGenerator(Tag[Service], key="@effect/ai/IdGenerator"):
    """Makes ids."""


def _generator(alphabet: str, prefix: str | None, separator: str, size: int) -> Service:
    def generate() -> Effect[str]:
        draws = fx.for_each(range(size), lambda _: Random.next())
        chars = draws.map(lambda values: "".join(alphabet[int(v * len(alphabet))] for v in values))
        return chars if prefix is None else chars.map(lambda body: f"{prefix}{separator}{body}")

    return Service(generate)


default_id_generator: Service = _generator(DEFAULT_ALPHABET, "id", "_", 16)


def make(
    *,
    alphabet: str = DEFAULT_ALPHABET,
    prefix: str | None = None,
    separator: str = "_",
    size: int = 16,
) -> Effect[Service, IllegalArgumentError]:
    """A generator; fails if ``separator`` is in ``alphabet``."""
    if separator in alphabet:
        message = f'The separator "{separator}" must not be part of the alphabet "{alphabet}".'
        return fx.fail(IllegalArgumentError(message))
    return fx.succeed(_generator(alphabet, prefix, separator, size))


def layer(
    *,
    alphabet: str = DEFAULT_ALPHABET,
    prefix: str | None = None,
    separator: str = "_",
    size: int = 16,
) -> L.Layer[IdGenerator, IllegalArgumentError, Never]:
    return L.effect(
        IdGenerator, make(alphabet=alphabet, prefix=prefix, separator=separator, size=size)
    )
