"""Tool call ids and approval ids are unique.

An approval answer names an approval id, its request names one call id,
and results are matched to calls by id, so each id must mean one thing:
within a provider response and against the prompt's history. The language
model checks each response here as it arrives, before any part is decoded
or any handler runs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from pyfect.ai import ai_error as E
from pyfect.ai import prompt as P


@dataclass(frozen=True)
class _Kind:
    part_type: str
    wire_key: str
    label: str


CALL = _Kind("tool-call", "id", "tool call id")
APPROVAL = _Kind("tool-approval-request", "approvalId", "approval id")
_KINDS = (CALL, APPROVAL)


def _part_id(part: P.AssistantMessagePart, kind: _Kind) -> str | None:
    if kind is CALL and isinstance(part, P.ToolCallPart):
        return part.id
    if kind is APPROVAL and isinstance(part, P.ToolApprovalRequestPart):
        return part.approval_id
    return None


def in_history(messages: Iterable[P.Message], kind: _Kind) -> list[str]:
    """Every ``kind`` id the assistant messages use, in order, repeats kept."""
    return [
        id
        for message in messages
        if isinstance(message, P.AssistantMessage)
        for part in message.content
        if (id := _part_id(part, kind)) is not None
    ]


def repeated(ids: Iterable[str]) -> frozenset[str]:
    seen: set[str] = set()
    twice: set[str] = set()
    for id in ids:
        (twice if id in seen else seen).add(id)
    return frozenset(twice)


class Ledger:
    """The ids a response may no longer use: those of the prompt and those
    the response has already sent."""

    def __init__(self, messages: Sequence[P.Message]) -> None:
        self._seen = {kind: set(in_history(messages, kind)) for kind in _KINDS}

    def admit(self, parts: Sequence[Mapping[str, object]], method: str) -> E.AiError | None:
        for part in parts:
            for kind in _KINDS:
                if part.get("type") != kind.part_type:
                    continue
                id = part.get(kind.wire_key)
                if not isinstance(id, str):
                    continue  # the response decoder reports it
                seen = self._seen[kind]
                if id in seen:
                    reason = E.InvalidResponseError(
                        description=f"{kind.label} {id!r} is used more than once"
                    )
                    return E.make(module="LanguageModel", method=method, reason=reason)
                seen.add(id)
        return None
