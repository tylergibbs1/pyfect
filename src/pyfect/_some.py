"""``Some``, on its own so ``pyfect.result`` and ``pyfect.option`` can both
use it without importing each other."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

A_co = TypeVar("A_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Some(Generic[A_co]):
    """A present value in an ``Option``: ``Some(None)`` is a present ``None``, unlike ``None``."""

    value: A_co


type Option[A] = Some[A] | None
