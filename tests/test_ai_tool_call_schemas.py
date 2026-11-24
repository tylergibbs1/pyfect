"""The schemas a tool call's failures and durable record are kept with are one node per tool,
so their codecs are derived once (codecs are memoized by node), not on every call. A new node
per call made a durable agent with a tool ledger derive about 2 ms of codecs on each call: the
ledger sweep of tests/test_ai_durable.py took 3.5 s of its 5 s timeout (flake hunt run
45306276279 timed it out).
"""

from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import tool as T
from pyfect.ai import tool_ledger
from pyfect.ai import toolkit as K
from pyfect.ai._call_schemas import call_schema
from pyfect.context import Context


class Params(TypedDict):
    n: int


Lookup = T.make("Lookup", parameters=S.Struct(Params), success=S.String, failure=S.String)
KIT = K.make(Lookup)
HANDLERS = KIT.to_layer(Lookup.handler(lambda params, _: fx.succeed(str(params["n"]))))


def _derived_once(schema: Any) -> bool:
    return S.to_codec_json(schema()).ast is S.to_codec_json(schema()).ast


def test_a_tools_failed_result_is_one_schema():
    assert _derived_once(lambda: T.failure_result_schema(Lookup))


@testing.effect
def test_a_toolkits_call_failures_are_one_schema():
    kit = yield from KIT.pipe(fx.provide(HANDLERS))
    assert _derived_once(lambda: kit.call_failure_schema("Lookup"))


@testing.effect
def test_a_guarded_toolkits_call_failures_are_one_schema():
    guarded = tool_ledger.guard(KIT, on_unknown="tell_model")
    kit = yield from guarded.pipe(fx.provide(HANDLERS)).pipe(fx.provide(tool_ledger.layer_memory))
    assert _derived_once(lambda: kit.call_failure_schema("Lookup"))


def test_a_schema_made_per_toolkit_kind_and_tool_is_made_once():
    tools: dict[str, T.AnyTool] = {"Lookup": Lookup}
    kit = K.WithHandler[Any, Any, Any, Any](tools, Context.empty())
    other = K.WithHandler[Any, Any, Any, Any](tools, Context.empty())
    made: list[str] = []

    def make(kind: str) -> Any:
        made.append(kind)
        return S.String

    for _ in range(2):
        call_schema(kit, "a", "Lookup", lambda: make("a"))
        call_schema(kit, "b", "Lookup", lambda: make("b"))
        call_schema(other, "a", "Lookup", lambda: make("other a"))
    assert made == ["a", "b", "other a"]
