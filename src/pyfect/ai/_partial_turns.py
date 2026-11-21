"""The turn an interrupt-safe chat commits when a call is cut short, and the tool calls
``resume`` runs again.

A provider takes a history only when each tool call it shows has its result: a turn cut
short between the model's tool calls and their results would make every later request
fail. ``closed`` turns a turn's parts so far into a valid history; ``unfinished`` and
``resumed`` find the calls it left unfinished and put their results in place.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, TypeIs

from pyfect.ai import prompt as P
from pyfect.ai import response as R

KEY = "pyfect/ai/Chat/InterruptSafe"
"""The provider-options key marking a tool result ``closed`` stood in with."""

_MARK = {"unfinished": True}

_UNFINISHED = {
    "type": "execution-interrupted",
    "reason": "Tool call execution was interrupted because the turn ended before it finished",
}


def _unfinished_result(call: R.AnyToolCallPart) -> R.AnyToolResultPart:
    return R.tool_result_part(
        id=call.id,
        name=call.name,
        is_failure=True,
        result=_UNFINISHED,
        encoded_result=_UNFINISHED,
        metadata={KEY: _MARK},
    )


def closed(parts: Sequence[Any], runs_handler: Callable[[str], bool]) -> list[Any]:
    """``parts`` (a turn's, in the order received) with each tool call answered: a call
    whose handler was to run and has no final result gets an ``execution-interrupted``
    one, and a provider-executed call without its result is dropped, since only the
    provider can answer it. Calls the application answers (client-executed tools, calls
    awaiting approval, unresolved calls) stay as a finished turn leaves them."""
    answered: set[str] = set()
    for part in parts:
        if isinstance(part, (R.ToolResultSuccess, R.ToolResultFailure)) and not part.preliminary:
            answered.add(part.id)
        elif isinstance(part, R.ToolApprovalRequestPart):
            answered.add(part.tool_call_id)
    calls: list[R.AnyToolCallPart] = [
        part for part in parts if isinstance(part, R.ToolCallPart) and part.id not in answered
    ]
    dropped = {call.id for call in calls if call.provider_executed}
    kept: list[Any] = [
        part for part in parts if not (isinstance(part, R.ToolCallPart) and part.id in dropped)
    ]
    added = [
        _unfinished_result(call)
        for call in calls
        if not call.provider_executed and runs_handler(call.name)
    ]
    return [*kept, *added]


def _is_unfinished(part: P.ToolMessagePart) -> TypeIs[P.ToolResultPart]:
    return isinstance(part, P.ToolResultPart) and part.options.get(KEY) == _MARK


@dataclass(frozen=True)
class _LastTurn:
    """The history's last assistant message, at ``index``, and the tool messages after it."""

    index: int
    assistant: P.AssistantMessage
    tools: tuple[P.ToolMessage, ...]


def _last_turn(history: P.Prompt) -> _LastTurn | None:
    """The last turn, when only tool messages follow its assistant message."""
    tools: list[P.ToolMessage] = []
    for index in range(len(history.content) - 1, -1, -1):
        match history.content[index]:
            case P.AssistantMessage() as assistant:
                return _LastTurn(index, assistant, tuple(reversed(tools)))
            case P.ToolMessage() as tool:
                tools.append(tool)
            case _:
                return None
    return None


def unfinished(history: P.Prompt) -> list[P.ToolCallPart]:
    """The tool calls of the history's last turn that ``closed`` answered for."""
    turn = _last_turn(history)
    if turn is None:
        return []
    ids = {part.id for tool in turn.tools for part in tool.content if _is_unfinished(part)}
    return [
        part
        for part in turn.assistant.content
        if isinstance(part, P.ToolCallPart) and part.id in ids
    ]


def resumed(history: P.Prompt, results: Sequence[Any]) -> P.Prompt:
    """``history`` with the stand-in result of each call in ``results`` replaced by its
    result there; a call that now awaits approval gets its approval request in the
    assistant message instead."""
    turn = _last_turn(history)
    if turn is None or not results:
        return history
    requests = [r for r in results if isinstance(r, R.ToolApprovalRequestPart)]
    by_id: dict[str, P.ToolMessagePart | None] = {r.tool_call_id: None for r in requests}
    answers = P.from_response_parts(
        [r for r in results if not isinstance(r, R.ToolApprovalRequestPart)]
    )
    for message in answers.content:
        if isinstance(message, P.ToolMessage):
            by_id.update(
                (part.id, part) for part in message.content if isinstance(part, P.ToolResultPart)
            )

    def answer(part: P.ToolMessagePart) -> list[P.ToolMessagePart]:
        if not _is_unfinished(part) or part.id not in by_id:
            return [part]
        found = by_id[part.id]
        return [] if found is None else [found]

    tools = [
        replace(tool, content=content)
        for tool in turn.tools
        if (content := [kept for part in tool.content for kept in answer(part)])
    ]
    added = [
        P.ToolApprovalRequestPart(approval_id=r.approval_id, tool_call_id=r.tool_call_id)
        for r in requests
    ]
    assistant = replace(turn.assistant, content=[*turn.assistant.content, *added])
    return P.from_messages([*history.content[: turn.index], assistant, *tools])
