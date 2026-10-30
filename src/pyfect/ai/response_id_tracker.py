"""Sending only the new part of a conversation (Effect's
``ResponseIdTracker``).

Providers with server-side conversation state take the previous response's
id and the messages after it. The tracker remembers which prompt messages
(by identity) were sent with which response; ``prepare_unsafe`` gives the
id and the messages after the last assistant message when every earlier
message was sent, and forgets everything otherwise.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pyfect._core import Effect
from pyfect.ai import prompt as P
from pyfect.context import Tag
from pyfect.effect import sync


@dataclass(frozen=True)
class PrepareResult:
    previous_response_id: str
    prompt: P.Prompt


class Service:
    __slots__ = ("_sent",)

    def __init__(self) -> None:
        self._sent: dict[int, tuple[object, str]] = {}

    def clear_unsafe(self) -> None:
        self._sent.clear()

    def mark_parts(self, parts: Sequence[object], response_id: str) -> None:
        for part in parts:
            self._sent[id(part)] = (part, response_id)

    def _get(self, message: object) -> str | None:
        entry = self._sent.get(id(message))
        return entry[1] if entry is not None and entry[0] is message else None

    def prepare_unsafe(self, prompt: P.Prompt) -> PrepareResult | None:
        messages = prompt.content
        result = self._prepare(messages)
        if result is None:
            self._sent.clear()
        return result

    def _prepare(self, messages: tuple[P.Message, ...]) -> PrepareResult | None:
        if not any(self._get(m) is not None for m in messages):
            return None
        last = next(
            (
                i
                for i in range(len(messages) - 1, -1, -1)
                if isinstance(messages[i], P.AssistantMessage)
            ),
            -1,
        )
        if last == -1:
            return None
        response_id: str | None = None
        for message in messages[:last]:
            response_id = self._get(message)
            if response_id is None:
                return None
        after = messages[last + 1 :]
        if response_id is None or not after:
            return None
        return PrepareResult(response_id, P.from_messages(after))


class ResponseIdTracker(Tag[Service], key="effect/ai/ResponseIdTracker"):
    """The tracker of the current conversation."""


make: Effect[Service] = sync(Service)

__all__ = ["PrepareResult", "ResponseIdTracker", "Service", "make"]
