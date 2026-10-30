"""A tool approval runs exactly the call it was issued for.

An approval request names only a tool call id, so tool call ids must be
unique: in one response, against the prompt's history, and in the history
an approval is resolved against. Otherwise approving one call runs another
call's parameters.
"""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as P
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.result import Err, Ok
from pyfect.stream import _constructors as streams


class Transfer(TypedDict):
    amount: float


class Done(TypedDict):
    ok: bool


TransferTool = T.make(
    "Transfer", parameters=S.Struct(Transfer), success=S.Struct(Done), needs_approval=True
)
FreeTool = T.make("Free", parameters=S.Struct(Transfer), success=S.Struct(Done))
Kit = K.make(TransferTool, FreeTool)

FINISH: lm.EncodedPart = {
    "type": "finish",
    "reason": "tool-calls",
    "usage": {"inputTokens": {"uncached": 1, "total": 1}, "outputTokens": {"total": 1}},
}


def _call(id: str, amount: float, name: str = "Transfer") -> lm.EncodedPart:
    return {"type": "tool-call", "id": id, "name": name, "params": {"amount": amount}}


def _layer(ran: list[float]) -> fx.Layer[Any]:
    def run(params: Transfer, _: object) -> fx.Effect[Done]:
        return fx.sync(lambda: ran.append(params["amount"])).as_(Done(ok=True))

    return Kit.to_layer(TransferTool.handler(run), FreeTool.handler(run))


def _run(method: str, prompt: P.RawInput, parts: list[lm.EncodedPart], ran: list[float]) -> Any:
    eff: fx.Effect[Any, Any, Any] = (
        lm.generate_text(prompt, toolkit=Kit)
        if method == "generateText"
        else lm.stream_text(prompt, toolkit=Kit).run_collect()
    )
    model = lm.make(
        generate_text=lambda _: fx.succeed(parts),
        stream_text=lambda _: streams.from_iterable(parts),
    )
    provided = eff.pipe(fx.provide(_layer(ran))).pipe(
        fx.provide_service_effect(lm.LanguageModel, model)
    )
    return provided.result()


def _reason(result: Any) -> E.AnyReason:
    assert isinstance(result, Err), result
    error: object = result.error
    assert isinstance(error, E.AiError), error
    return error.reason


METHODS = pytest.mark.parametrize("method", ["generateText", "streamText"])


@METHODS
@testing.effect
def test_duplicate_call_ids_in_one_response_are_refused(method: str):
    ran: list[float] = []
    parts = [_call("c1", 10), _call("c1", 10000), FINISH]
    result = yield _run(method, "pay", parts, ran)
    assert isinstance(_reason(result), E.InvalidResponseError)
    assert ran == []


@METHODS
@testing.effect
def test_duplicate_ids_refused_for_tools_without_approval(method: str):
    ran: list[float] = []
    parts = [_call("c1", 1, "Free"), _call("c1", 2, "Free"), FINISH]
    result = yield _run(method, "pay", parts, ran)
    assert isinstance(_reason(result), E.InvalidResponseError)


@METHODS
@testing.effect
def test_response_reusing_a_history_call_id_is_refused(method: str):
    """An unanswered request for ``c1`` must not be rebound to a later call
    that reuses ``c1``."""
    ran: list[float] = []
    history = [
        P.UserMessage(content=[P.TextPart(text="pay 10")]),
        P.AssistantMessage(
            content=[
                P.ToolCallPart(id="c1", name="Transfer", params={"amount": 10}),
                P.ToolApprovalRequestPart(approval_id="a1", tool_call_id="c1"),
            ]
        ),
        P.UserMessage(content=[P.TextPart(text="hm")]),
    ]
    result = yield _run(method, P.from_messages(history), [_call("c1", 10000), FINISH], ran)
    assert isinstance(_reason(result), E.InvalidResponseError)
    assert ran == []


def _ambiguous_history(first: bool, second: bool) -> P.Prompt:
    return P.from_messages(
        [
            P.UserMessage(content=[P.TextPart(text="pay")]),
            P.AssistantMessage(
                content=[
                    P.ToolCallPart(id="c1", name="Transfer", params={"amount": 10}),
                    P.ToolApprovalRequestPart(approval_id="a1", tool_call_id="c1"),
                    P.ToolCallPart(id="c1", name="Transfer", params={"amount": 10000}),
                    P.ToolApprovalRequestPart(approval_id="a2", tool_call_id="c1"),
                ]
            ),
            P.ToolMessage(
                content=[
                    P.ToolApprovalResponsePart(approval_id="a1", approved=first),
                    P.ToolApprovalResponsePart(approval_id="a2", approved=second),
                ]
            ),
        ]
    )


@METHODS
@pytest.mark.parametrize(("first", "second"), [(True, False), (True, True)])
@testing.effect
def test_approval_for_an_ambiguous_call_id_is_refused(method: str, first: bool, second: bool):
    ran: list[float] = []
    stop: list[lm.EncodedPart] = [{**FINISH, "reason": "stop"}]
    result = yield _run(method, _ambiguous_history(first, second), stop, ran)
    assert isinstance(_reason(result), E.InvalidUserInputError)
    assert ran == []


@METHODS
@testing.effect
def test_distinct_ids_still_resolve(method: str):
    ran: list[float] = []
    parts = [_call("c1", 1, "Free"), _call("c2", 2, "Free"), FINISH]
    result = yield _run(method, "pay", parts, ran)
    assert isinstance(result, Ok), result
    assert sorted(ran) == [1, 2]


def _approval(approval_id: str, call_id: str) -> lm.EncodedPart:
    return {"type": "tool-approval-request", "approvalId": approval_id, "toolCallId": call_id}


@METHODS
@testing.effect
def test_response_repeating_an_approval_id_is_refused(method: str):
    """A provider may send its own approval requests; two with one approval
    id would let an answer shown for one call approve the other."""
    ran: list[float] = []
    parts = [
        _call("c1", 10),
        _call("c2", 10000),
        _approval("x", "c1"),
        _approval("x", "c2"),
        FINISH,
    ]
    result = yield _run(method, "pay", parts, ran)
    assert isinstance(_reason(result), E.InvalidResponseError)
    assert ran == []


@METHODS
@testing.effect
def test_response_reusing_a_history_approval_id_is_refused(method: str):
    ran: list[float] = []
    history = [
        P.UserMessage(content=[P.TextPart(text="pay 10")]),
        P.AssistantMessage(
            content=[
                P.ToolCallPart(id="c1", name="Transfer", params={"amount": 10}),
                P.ToolApprovalRequestPart(approval_id="a1", tool_call_id="c1"),
            ]
        ),
        P.UserMessage(content=[P.TextPart(text="hm")]),
    ]
    parts = [_call("c2", 10000), _approval("a1", "c2"), FINISH]
    result = yield _run(method, P.from_messages(history), parts, ran)
    assert isinstance(_reason(result), E.InvalidResponseError)
    assert ran == []


@METHODS
@testing.effect
def test_answer_to_a_repeated_approval_id_is_refused(method: str):
    ran: list[float] = []
    history = P.from_messages(
        [
            P.UserMessage(content=[P.TextPart(text="pay")]),
            P.AssistantMessage(
                content=[
                    P.ToolCallPart(id="c1", name="Transfer", params={"amount": 10}),
                    P.ToolApprovalRequestPart(approval_id="x", tool_call_id="c1"),
                    P.ToolCallPart(id="c2", name="Transfer", params={"amount": 10000}),
                    P.ToolApprovalRequestPart(approval_id="x", tool_call_id="c2"),
                ]
            ),
            P.ToolMessage(content=[P.ToolApprovalResponsePart(approval_id="x", approved=True)]),
        ]
    )
    stop: list[lm.EncodedPart] = [{**FINISH, "reason": "stop"}]
    result = yield _run(method, history, stop, ran)
    assert isinstance(_reason(result), E.InvalidUserInputError)
    assert ran == []
