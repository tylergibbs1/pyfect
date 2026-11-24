"""Durable agent loops: every ``LanguageModel`` request and every tool handler run inside
a workflow becomes one of its activities, so a crashed run resumes where it stopped::

    AgentLive = Agent.to_layer(run_agent).pipe(
        fx.layer.provide_merge(durable.layer),
        # then the LanguageModel, the toolkit's handlers and the workflow engine
    )

The agent's code does not change. Outside a workflow, and inside an activity (whose result
already covers what it does), ``layer`` changes nothing.

Each step's activity is named by its place in the run, so a replay finds it again:
``pyfect/ai/<n>/model`` for the run's ``n``-th model request, and
``pyfect/ai/<n>/tool/<i>`` for the ``i``-th tool call of that request's response (both
from 1). A tool call that no response of the run made (a call ``WithHandler.handle`` was
given directly) is ``pyfect/ai/handler/<k>``, the run's ``k``-th. The numbers come in the
order the run makes its requests, so model requests a run makes concurrently need that
order to be the same on every replay.

An activity stores the step's output and a hash of its request: the prompt, the tools
offered, the tool choice and the response format, or the tool's name and the parameters
the model sent. The prompt itself is not stored (the run rebuilds it on replay), so what
a run stores grows with each step's output, not with the conversation so far. A replay
whose request hashes differently from the one stored dies with ``RequestDiverged``: the
code changed under a running execution, and reusing the stored output would answer a
different question. Annotate the workflow with ``workflow.SuspendOnFailure`` to keep such
an execution resumable after a rollback.

A streamed request is one activity too: the provider's stream is read to its end, and the
caller gets its parts as one chunk, on the first run and on every replay alike, so a
consumer never sees a part twice when a crash cuts a stream short.
"""

from __future__ import annotations

import copy
import hashlib
import threading
import weakref
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any, Never, NotRequired, TypedDict, cast

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_text import stringify
from pyfect._public import publish
from pyfect._text_keys import key_bytes
from pyfect.ai import _tool_outcomes as outcomes
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as P
from pyfect.ai import toolkit as K
from pyfect.ai._budget import Precounted, tool_call
from pyfect.ai._call_schemas import call_schema
from pyfect.ai._handler_hook import Handled, HandlerHook
from pyfect.ai._tool_outcomes import Outcome
from pyfect.ai.ai_error import AiError
from pyfect.ai.tool import (
    AnyTool,
    FailureOrigin,
    get_description,
    get_json_schema,
    get_json_schema_from_schema,
    is_client_executed,
)
from pyfect.ai.toolkit import HandlerResult
from pyfect.cause import Cause
from pyfect.layer import Layer
from pyfect.stream import Stream
from pyfect.stream import _constructors as StreamC
from pyfect.workflow import activity
from pyfect.workflow._activity_hook import RunningActivity
from pyfect.workflow._services import WorkflowInstance, WorkflowInstanceService


class RequestDiverged(S.TaggedError, identifier="pyfect/ai/Durable/RequestDiverged"):
    """The replay of ``step`` made a request hashing to ``requested``, and the run stored
    the output of one hashing to ``recorded``: the workflow's code changed under it."""

    step: str = S.field(S.String)
    recorded: str = S.field(S.String)
    requested: str = S.field(S.String)

    @property
    def message(self) -> str:
        return (
            f"{self.step}: the replayed request ({self.requested[:12]}) differs from the "
            f"recorded one ({self.recorded[:12]})"
        )


# Request hashes --------------------------------------------------------------------------

_encode_message = S.encode_unknown_sync(S.to_codec_json(P.MESSAGE))
_prompt_chains: OrderedDict[int, tuple[P.Message, P.Message | None, str]] = OrderedDict()
_PROMPT_CHAINS = 4096
"""For each message, by identity: the message before it and the digest of the prompt up to
it. A run's prompt grows by a few messages a turn and keeps the ones before, so hashing it
digests only the new messages, and a turn's hash costs the same at turn 100 as at turn 1."""
_tool_documents: dict[int, tuple[AnyTool, object]] = {}
_cache_lock = threading.Lock()


def _digest(document: object) -> str:
    return hashlib.sha256(key_bytes(stringify(document, sort_keys=True))).hexdigest()


def _prompt_digest(messages: Sequence[P.Message]) -> str:
    """The digest of ``messages``, each message's digest chained onto the ones before."""
    done, chain = 0, ""
    with _cache_lock:
        for end in range(len(messages), 0, -1):
            found = _prompt_chains.get(id(messages[end - 1]))
            before = messages[end - 2] if end > 1 else None
            if found is not None and found[0] is messages[end - 1] and found[1] is before:
                _prompt_chains.move_to_end(id(messages[end - 1]))
                done, chain = end, found[2]
                break
    for index in range(done, len(messages)):
        message = messages[index]
        chain = _digest([chain, _digest(_encode_message(message))])
        with _cache_lock:
            before = messages[index - 1] if index > 0 else None
            _prompt_chains[id(message)] = (message, before, chain)
            if len(_prompt_chains) > _PROMPT_CHAINS:
                _prompt_chains.popitem(last=False)
    return chain


def _tool_document(tool: AnyTool) -> object:
    """What of ``tool`` the model sees, computed once per tool."""
    with _cache_lock:
        found = _tool_documents.get(id(tool))
    if found is not None and found[0] is tool:
        return found[1]
    document = {
        "name": tool.name,
        "description": get_description(tool),
        "parameters": get_json_schema(tool),
    }
    with _cache_lock:
        _tool_documents[id(tool)] = (tool, document)
    return document


def request_hash(options: lm.ProviderOptions, *, streamed: bool) -> str:
    """The hash a model request is stored with: its prompt, tools, tool choice and
    response format, and whether it was streamed."""
    response_format: object = (
        {"type": "text"}
        if isinstance(options.response_format, lm.TextFormat)
        else {
            "type": "json",
            "name": options.response_format.object_name,
            "schema": get_json_schema_from_schema(options.response_format.schema),
        }
    )
    return _digest(
        {
            "streamed": streamed,
            "prompt": _prompt_digest(options.prompt.content),
            "tools": [_tool_document(tool) for tool in options.tools],
            "toolChoice": options.tool_choice,
            "responseFormat": response_format,
        }
    )


def call_hash(tool_name: str, params: object) -> str:
    """The hash a tool call is stored with: the tool's name and the parameters the model
    sent."""
    return _digest({"tool": tool_name, "params": params})


# A run's steps ---------------------------------------------------------------------------


class _Steps:
    """The step numbers one run of a workflow has given out."""

    __slots__ = ("calls", "handlers", "lock", "requests")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests = 0
        self.handlers = 0
        self.calls: dict[str, str] = {}

    def next_request(self) -> int:
        with self.lock:
            self.requests += 1
            return self.requests

    def record_calls(self, request: int, parts: Sequence[lm.EncodedPart]) -> None:
        calls = [p for p in parts if p.get("type") == "tool-call" and isinstance(p.get("id"), str)]
        with self.lock:
            for index, part in enumerate(calls, start=1):
                self.calls[cast("str", part["id"])] = f"pyfect/ai/{request}/tool/{index}"

    def call_step(self, tool_call_id: str | None) -> str:
        with self.lock:
            step = None if tool_call_id is None else self.calls.get(tool_call_id)
            if step is not None:
                return step
            self.handlers += 1
            return f"pyfect/ai/handler/{self.handlers}"


_runs: weakref.WeakKeyDictionary[WorkflowInstanceService, _Steps] = weakref.WeakKeyDictionary()
_runs_lock = threading.Lock()


def _steps(instance: WorkflowInstanceService) -> _Steps:
    with _runs_lock:
        found = _runs.get(instance)
        if found is None:
            found = _runs[instance] = _Steps()
        return found


def _durable_run() -> Effect[WorkflowInstanceService | None]:
    """The run of the workflow this effect belongs to, unless it runs in an activity."""
    return RunningActivity().flat_map(
        lambda inside: (
            fx.succeed(None)
            if inside
            else fx.service_option(WorkflowInstance).map(
                lambda found: None if found is None else found.value
            )
        )
    )


# Steps as activities ---------------------------------------------------------------------


class _Succeeded(TypedDict):
    hash: str
    success: object


class _Failed(TypedDict):
    hash: str
    failure: object


def _record_schema(success: S.Top, failure: S.Top) -> S.Top:
    return S.Union(
        S.Struct(_Succeeded, success=cast("Any", success)),
        S.Struct(_Failed, failure=cast("Any", failure)),
    )


_MODEL_RECORD = _record_schema(S.Array(S.Unknown), cast("S.Top", AiError))


class _Outcome(TypedDict):
    is_failure: bool
    encoded_result: object
    failure_origin: str | None
    returned: NotRequired[bool]
    """Missing in records of releases up to 0.6.22, which never stored a returned failure
    of a tool in ``"error"`` mode."""


_OUTCOME = S.Struct(_Outcome, encoded_result=S.Unknown)


def _tool_record(kit: K.WithHandler[Any, Any, Any, Any], name: str) -> S.Top:
    """A tool call's record: the result the model saw, or a failure the call gave its
    caller instead, any the toolkit (wrapped by a tool ledger, say) can give."""
    return call_schema(
        kit, "durable record", name, lambda: _record_schema(_OUTCOME, kit.call_failure_schema(name))
    )


def _step[A](
    name: str, digest: str, record: S.Top, run: Effect[A, Any, Any]
) -> Effect[A, Any, Any]:
    """``run`` as the activity ``name``, stored with ``digest``; a stored one with another
    hash dies with ``RequestDiverged``."""
    recorded = run.match(
        on_success=lambda value: {"hash": digest, "success": value},
        on_failure=lambda error: {"hash": digest, "failure": error},
    )
    step = activity.make(name=name, success=cast("Any", record), execute=recorded)

    def replayed(stored: dict[str, Any]) -> Effect[A, Any]:
        if stored["hash"] != digest:
            return fx.die(RequestDiverged(step=name, recorded=stored["hash"], requested=digest))
        if "failure" in stored:
            return fx.fail(stored["failure"])
        return fx.succeed(cast("A", stored["success"]))

    return cast("Effect[dict[str, Any], Never, Any]", step).flat_map(replayed)


def _generate(inner: lm.GenerateFn) -> lm.GenerateFn:
    def generate(options: lm.ProviderOptions) -> Effect[Sequence[lm.EncodedPart], AiError, Any]:
        def in_run(instance: WorkflowInstanceService | None) -> Effect[Any, AiError, Any]:
            if instance is None:
                return inner(options)
            steps = _steps(instance)
            request = steps.next_request()
            digest = request_hash(options, streamed=False)
            parts = _step(
                f"pyfect/ai/{request}/model",
                digest,
                _MODEL_RECORD,
                fx.suspend(lambda: inner(options)),
            )
            return parts.tap(lambda found: fx.sync(lambda: steps.record_calls(request, found)))

        return _durable_run().flat_map(in_run)

    return generate


def _stream(inner: lm.StreamFn) -> lm.StreamFn:
    def stream(options: lm.ProviderOptions) -> Stream[lm.EncodedPart, AiError, Any]:
        def in_run(instance: WorkflowInstanceService | None) -> Effect[Stream[Any, Any, Any]]:
            if instance is None:
                return fx.succeed(inner(options))
            steps = _steps(instance)
            request = steps.next_request()
            digest = request_hash(options, streamed=True)
            collected = StreamC.suspend(lambda: inner(options)).run_collect().map(list)
            parts = _step(f"pyfect/ai/{request}/model", digest, _MODEL_RECORD, collected)
            recorded = parts.tap(lambda found: fx.sync(lambda: steps.record_calls(request, found)))
            return fx.succeed(StreamC.unwrap(recorded.map(lambda found: StreamC.make(*found))))

        return StreamC.unwrap(_durable_run().flat_map(in_run))

    return stream


def _outcome(tool: AnyTool, handled: Handled) -> Effect[_Outcome, Any, Any]:
    """The final result of the call ``handled`` runs, as the model sees it."""

    def final(results: Sequence[HandlerResult]) -> Effect[Outcome]:
        last = [r for r in results if not r.preliminary]
        if not last:
            return fx.die(ValueError(f'Tool "{tool.name}" did not produce a final result'))
        return fx.succeed(outcomes.of_result(last[-1]))

    def failed(cause: Cause[Any]) -> Effect[Outcome, Any]:
        return outcomes.of_failure(tool, cause).flat_map(
            lambda outcome: fx.fail_cause(cause) if outcome is None else fx.succeed(outcome)
        )

    def stored(o: Outcome) -> _Outcome:
        record = _Outcome(
            is_failure=o.is_failure,
            encoded_result=o.encoded_result,
            failure_origin=o.failure_origin,
        )
        # Only where it changes the replay, so every other record is stored as before.
        if o.returned and tool.failure_mode == "error":
            record["returned"] = True
        return record

    collected = handled.flat_map(lambda stream: stream.run_collect()).flat_map(final)
    return collected.catch_cause(failed).map(stored)


def _replayed(tool: AnyTool, failures: S.Top, stored: _Outcome) -> Handled:
    outcome = Outcome(
        stored["is_failure"],
        stored["encoded_result"],
        cast("FailureOrigin | None", stored["failure_origin"]),
        stored.get("returned", False),
    )

    # A stored result that no longer decodes is a defect: the tool's schemas changed.
    return outcomes.replay(tool, outcome, lambda error: error, failures=failures).or_die()


def _call(
    kit: K.WithHandler[Any, Any, Any, Any], name: str, params: object, tool_call_id: str
) -> Handled:
    handled = kit.handle(name, params, tool_call_id)
    tool = kit.tools.get(name)
    if tool is None or is_client_executed(tool):
        return handled
    known = tool

    def in_run(instance: WorkflowInstanceService | None) -> Handled:
        if instance is None:
            return handled
        step = _steps(instance).call_step(tool_call_id)
        # Counted here, on the first run and on every replay; the handler's run inside
        # the activity does not count it again.
        inner = handled.pipe(fx.provide_service(Precounted, tool_call_id))
        record = _tool_record(kit, name)
        stored = _step(step, call_hash(name, params), record, _outcome(known, inner))
        failures = kit.call_failure_schema(name)
        return tool_call(tool_call_id).and_then(
            stored.flat_map(lambda found: _replayed(known, failures, found))
        )

    return _durable_run().flat_map(in_run)


def _durable_model(model: lm.Service) -> lm.Service:
    return copy.replace(
        model,
        _generate=_generate(model._generate),  # pyright: ignore[reportPrivateUsage]
        _stream=_stream(model._stream),  # pyright: ignore[reportPrivateUsage]
    )


layer: Layer[lm.LanguageModel, Never, lm.LanguageModel] = cast(
    "Layer[lm.LanguageModel, Never, lm.LanguageModel]",
    fx.layer.merge(
        fx.layer.effect(lm.LanguageModel, lm.LanguageModel().map(_durable_model)),
        fx.layer.succeed(HandlerHook, _call),
    ),
)
"""The ``LanguageModel`` in context, with each request and each tool call made
inside a workflow an activity of it (see the module docstring)."""


__all__ = ["RequestDiverged", "call_hash", "layer", "request_hash"]

publish(globals())
