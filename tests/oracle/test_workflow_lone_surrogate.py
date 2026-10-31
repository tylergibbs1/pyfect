"""A lone surrogate in an idempotency key or a name is encoded as
``TextEncoder`` encodes it, U+FFFD (QA ai-workflow WF-2). Expected values
are Effect 4.0.6's under Node."""

from __future__ import annotations

from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.workflow import durable_deferred, workflow

_LONE = "a\ud800b"


class _Payload(TypedDict):
    k: str


def test_an_execution_id_of_a_key_with_a_lone_surrogate():
    flow = workflow.make("Lone", payload=S.Struct(_Payload), idempotency_key=lambda p: p["k"])
    assert fx.run_sync(flow.execution_id({"k": _LONE})) == "8cccadc2aef10c793147c031ea464bdd"


def test_a_token_of_a_workflow_named_with_a_lone_surrogate():
    flow = workflow.make(_LONE, payload=S.Struct(_Payload), idempotency_key=lambda p: p["k"])
    token = durable_deferred.make("d").token_from_execution_id(workflow=flow, execution_id="e")
    assert token == "WyJhXHVkODAwYiIsImUiLCJkIl0"
