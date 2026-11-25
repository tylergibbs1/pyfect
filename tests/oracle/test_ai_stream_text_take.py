"""``stream_text(...).take(n)`` starts the tool handlers of the calls the
model sent, as Effect does since it forks a toolkit handler with
``startImmediately`` (Effect 4.1.5, ae947a3). Run under Node, Effect at that
commit logs both handler starts for ``take`` 1, 2 or 3 of a stream with two
tool calls, a text delta and the finish; at the commit before it, and in
Effect 4.0.6 (QA ai-workflow AI-1), it logged none."""

from __future__ import annotations

from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect.ai import language_model as lm
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K

from ._ai import with_language_model


class _Params(TypedDict):
    ms: float


_TOOL = T.make("T", parameters=S.Struct(_Params), success=S.String)
_TOOLKIT = K.make(_TOOL)
_FINISH: Any = {
    "type": "finish",
    "reason": "tool-calls",
    "usage": {"inputTokens": {"uncached": 1, "total": 1}, "outputTokens": {"total": 1}},
}


def _call(id: str, ms: int) -> Any:
    return {"type": "tool-call", "id": id, "name": "T", "params": {"ms": ms}}


@pytest.mark.parametrize("n", [1, 2, 3])
def test_take_starts_the_tool_handlers_of_the_calls_sent(n: int) -> None:
    log: list[str] = []

    def handler(params: _Params, _: object) -> fx.Effect[str]:
        ms = int(params["ms"])
        return (
            fx.sync(lambda: log.append(f"start{ms}"))
            .and_then(fx.sleep(fx.duration.millis(ms)))
            .as_("d")
        )

    parts = [_call("a", 80), _call("b", 10), {"type": "text-delta", "id": "t", "delta": "x"}]
    taken = fx.run_blocking(
        lm.stream_text("hi", toolkit=_TOOLKIT)
        .take(n)
        .run_collect()
        .pipe(with_language_model(stream_text=[*parts, _FINISH]))
        .pipe(fx.provide(_TOOLKIT.to_layer(_TOOL.handler(handler))))
    )
    fx.run_blocking(fx.sleep("100 millis"))
    assert [part.type for part in taken] == [p["type"] for p in parts[:n]]
    assert log == ["start80", "start10"]
