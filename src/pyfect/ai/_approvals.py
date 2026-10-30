"""Tool approvals in a prompt (Effect's tool approval helpers).

A tool with ``needs_approval`` does not run when the model calls it: the
response carries a ``tool-approval-request``. The user's answer comes back
in the next prompt as a ``tool-approval-response``; before calling the
model again, approved calls run and denied ones get an ``execution-denied``
result, and the answered requests and responses are removed from the
prompt the provider sees.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Never, cast

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai import _tool_call_ids as Ids
from pyfect.ai import ai_error as E
from pyfect.ai import prompt as P
from pyfect.ai import response as R
from pyfect.ai import toolkit as K
from pyfect.ai.tool import AnyTool, NeedsApprovalContext

if TYPE_CHECKING:
    from pyfect._concurrency import Concurrency


@dataclass(frozen=True)
class Approval:
    """A user's answer to an approval request, with the call it is for."""

    approval_id: str
    tool_call_id: str
    approved: bool
    reason: str | None
    tool_call: P.ToolCallPart | None


@dataclass(frozen=True)
class Approvals:
    """Every answer in a prompt, and those whose call has no result yet."""

    approved: tuple[Approval, ...] = ()
    denied: tuple[Approval, ...] = ()
    pending_approved: tuple[Approval, ...] = ()
    pending_denied: tuple[Approval, ...] = ()
    ambiguous: frozenset[str] = frozenset()
    """Approval ids of answers that cannot say which call they approve:
    more than one request in the prompt uses the approval id, or more than
    one tool call uses its call id."""

    @property
    def pending(self) -> tuple[Approval, ...]:
        return (*self.pending_approved, *self.pending_denied)


def collect(messages: Sequence[P.Message]) -> Approvals:
    """The approval answers in ``messages`` that match a request."""
    requests: dict[str, str] = {}
    responses: list[P.ToolApprovalResponsePart] = []
    calls: dict[str, P.ToolCallPart] = {}
    results: set[str] = set()
    for message in messages:
        if isinstance(message, P.AssistantMessage):
            for part in message.content:
                if isinstance(part, P.ToolApprovalRequestPart):
                    requests[part.approval_id] = part.tool_call_id
                elif isinstance(part, P.ToolCallPart):
                    calls[part.id] = part
        elif isinstance(message, P.ToolMessage):
            for part in message.content:
                if isinstance(part, P.ToolApprovalResponsePart):
                    responses.append(part)
                else:
                    results.add(part.id)
    approved: list[Approval] = []
    denied: list[Approval] = []
    pending_approved: list[Approval] = []
    pending_denied: list[Approval] = []
    for response in responses:
        call_id = requests.get(response.approval_id)
        if call_id is None:
            continue
        approval = Approval(
            response.approval_id, call_id, response.approved, response.reason, calls.get(call_id)
        )
        (approved if response.approved else denied).append(approval)
        if call_id not in results:
            (pending_approved if response.approved else pending_denied).append(approval)
    repeated_calls = Ids.repeated(Ids.in_history(messages, Ids.CALL))
    repeated_approvals = Ids.repeated(Ids.in_history(messages, Ids.APPROVAL))
    ambiguous = frozenset(
        a.approval_id
        for a in (*approved, *denied)
        if a.tool_call_id in repeated_calls or a.approval_id in repeated_approvals
    )
    return Approvals(
        tuple(approved), tuple(denied), tuple(pending_approved), tuple(pending_denied), ambiguous
    )


def strip_resolved(prompt: P.Prompt, approvals: Approvals) -> P.Prompt:
    """``prompt`` without the answered approval requests and responses
    (providers reject approvals they did not issue); a message left empty
    is dropped."""
    resolved = {a.approval_id for a in (*approvals.approved, *approvals.denied)}
    if not resolved:
        return prompt
    messages: list[P.Message] = []
    for message in prompt.content:
        if isinstance(message, P.AssistantMessage):
            content = [
                part
                for part in message.content
                if not (
                    isinstance(part, P.ToolApprovalRequestPart) and part.approval_id in resolved
                )
            ]
            if content:
                messages.append(replace(message, content=content))
        elif isinstance(message, P.ToolMessage):
            kept = [
                part
                for part in message.content
                if not (
                    isinstance(part, P.ToolApprovalResponsePart) and part.approval_id in resolved
                )
            ]
            if kept:
                messages.append(replace(message, content=kept))
        else:
            messages.append(message)
    return P.from_messages(messages)


def needs_approval(
    tool: AnyTool, call: Mapping[str, object], messages: Sequence[P.Message]
) -> Effect[bool, Never, Any]:
    """Whether ``call`` waits for approval: the tool's flag, or its function
    of the decoded parameters (a failure there counts as no)."""
    check = tool.needs_approval
    if check is None or isinstance(check, bool):
        return fx.succeed(bool(check))
    context = NeedsApprovalContext(cast("str", call["id"]), tuple(messages))

    def decide(params: object) -> Effect[bool, Any, Any]:
        result = check(params, context)
        return result if isinstance(result, Effect) else fx.succeed(result)

    decode = cast("Any", S.decode_unknown_effect(tool.parameters_schema))(call.get("params"))
    return (
        cast("Effect[object, Any, Any]", decode).flat_map(decide).or_else_succeed(lambda _: False)
    )


def _error(method: str, reason: E.AnyReason) -> E.AiError:
    return E.make(module="LanguageModel", method=method, reason=reason)


def pending_check(
    approvals: Approvals, kit: K.WithHandler[Any, Any, Any, Any] | None, method: str
) -> E.AiError | None:
    """The error a prompt's pending approvals raise: without a toolkit to
    answer them, approving a tool the toolkit lacks, or not naming exactly
    one call."""
    if approvals.ambiguous:
        ids = ", ".join(sorted(repr(id) for id in approvals.ambiguous))
        description = f"tool approvals do not name exactly one tool call: {ids}"
        return _error(method, E.InvalidUserInputError(description=description))
    if kit is None or not kit.tools:
        if not approvals.pending:
            return None
        names = [a.tool_call.name for a in approvals.pending if a.tool_call is not None]
        return _error(method, E.ToolkitRequiredError(pending_approvals=names))
    for approval in approvals.pending_approved:
        if approval.tool_call is not None and approval.tool_call.name not in kit.tools:
            available = tuple(kit.tools)
            reason = E.ToolNotFoundError(
                tool_name=approval.tool_call.name, available_tools=available
            )
            return _error(method, reason)
    return None


def _run_approved(
    approval: Approval, kit: K.WithHandler[Any, Any, Any, Any]
) -> Effect[R.AnyToolResultPart, Any, Any]:
    call = approval.tool_call
    if call is None:
        return fx.die(ValueError("Approval missing tool call reference"))
    if call.name not in kit.tools:
        reason = E.ToolNotFoundError(tool_name=call.name, available_tools=tuple(kit.tools))
        return fx.fail(_error("generateText", reason))

    def final(results: Sequence[K.HandlerResult]) -> Effect[R.AnyToolResultPart]:
        finals = [result for result in results if not result.preliminary]
        if not finals:
            return fx.die(ValueError("Tool handler did not produce a final result"))
        last = finals[-1]
        return fx.succeed(
            R.tool_result_part(
                id=approval.tool_call_id,
                name=call.name,
                is_failure=last.is_failure,
                result=last.result,
                encoded_result=last.encoded_result,
            )
        )

    handled = kit.handle(call.name, call.params, approval.tool_call_id)
    return handled.flat_map(lambda stream: stream.run_collect()).flat_map(final)


def pre_resolve(
    approvals: Approvals, kit: K.WithHandler[Any, Any, Any, Any], concurrency: Concurrency
) -> Effect[list[R.AnyToolResultPart], Any, Any]:
    """The results of the pending approved calls (run now) and of the
    pending denied ones (``execution-denied``)."""
    approved = fx.for_each(
        approvals.pending_approved,
        lambda approval: _run_approved(approval, kit),
        concurrency=concurrency,
    )

    def denials() -> list[R.AnyToolResultPart]:
        return [
            denied_result(denial.tool_call_id, denial.tool_call.name, denial.reason)
            for denial in approvals.pending_denied
            if denial.tool_call is not None
        ]

    return approved.map(lambda results: [*results, *denials()])


def with_results(prompt: P.Prompt, results: Sequence[R.AnyToolResultPart]) -> P.Prompt:
    """``prompt`` followed by the pre-resolved ``results``."""
    if not results:
        return prompt
    return P.from_messages([*prompt.content, *P.from_response_parts(results).content])


def denied_result(call_id: str, name: str, reason: str | None) -> R.AnyToolResultPart:
    result = {"type": "execution-denied", "reason": reason}
    return R.tool_result_part(
        id=call_id, name=name, is_failure=True, result=result, encoded_result=result
    )
