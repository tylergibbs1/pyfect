"""Counting and truncating a prompt's tokens (Effect's ``Tokenizer``)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import pyfect as fx
from pyfect._core import Effect
from pyfect.ai import prompt as P
from pyfect.ai.ai_error import AiError
from pyfect.context import Tag

type Tokenize = Callable[[P.Prompt], Effect[Sequence[int], AiError]]


@dataclass(frozen=True)
class Service:
    _tokenize: Tokenize

    def tokenize(self, input: P.RawInput) -> Effect[Sequence[int], AiError]:
        """The token ids of ``input`` (a string, messages or a ``Prompt``,
        made into a ``Prompt`` first); fails with the tokenizer's
        ``AiError``."""
        return fx.suspend(lambda: self._tokenize(P.make(input)))

    def truncate(self, input: P.RawInput, tokens: int) -> Effect[P.Prompt, AiError]:
        """The latest messages of ``input`` that fit in ``tokens``."""
        return fx.suspend(lambda: _truncate(P.make(input).content, (), self._tokenize, tokens))


class Tokenizer(Tag[Service], key="effect/ai/Tokenizer"):
    """A model's tokenizer."""


def make(*, tokenize: Tokenize) -> Service:
    return Service(tokenize)


def _truncate(
    remaining: tuple[P.Message, ...],
    kept: tuple[P.Message, ...],
    tokenize: Tokenize,
    max_tokens: int,
) -> Effect[P.Prompt, AiError]:
    if not remaining:
        return fx.succeed(P.from_messages(kept))
    candidate = (remaining[-1], *kept)
    return tokenize(P.from_messages(candidate)).flat_map(
        lambda tokens: (
            fx.succeed(P.from_messages(kept))
            if len(tokens) > max_tokens
            else _truncate(remaining[:-1], candidate, tokenize, max_tokens)
        )
    )


__all__ = [
    "AiError",
    "Service",
    "Tokenize",
    "Tokenizer",
    "make",
]
