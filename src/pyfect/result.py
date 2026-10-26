"""``Ok[A] | Err[E]``: a typed error as a plain value (``Effect.result()``)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Ok[A]:
    value: A


@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E


type Result[A, E] = Ok[A] | Err[E]
