"""A schema's canonical codecs are derived once per schema node, as Effect memoizes its codec
derivations by AST, and the memo does not keep a schema alive.

A derivation is counted through a declaration's codec annotation, which each derivation of the
declaration calls once.
"""

from __future__ import annotations

import gc
import weakref
from collections.abc import Callable
from typing import Any, TypeIs

from oracle import _cluster_workflows as W

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import testing
from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.workflow import Complete, workflow

type LinkFactory = Callable[[tuple[ast.AST, ...]], ast.Link]


def _counted() -> tuple[list[int], LinkFactory]:
    calls = [0]

    def link(_parameters: tuple[ast.AST, ...]) -> ast.Link:
        calls[0] += 1
        same: T.Transformation[str, str] = T.passthrough()
        return ast.Link(S.String.ast, same)

    return calls, link


def _is_text(value: object) -> TypeIs[str]:
    return isinstance(value, str)


def _text(**annotations: LinkFactory) -> S.Bottom[str, Any, Any, Any]:
    return S.declare(_is_text, **annotations)


def test_a_json_codec_is_derived_once_per_schema():
    calls, link = _counted()
    schema = S.Array(_text(to_codec_json=link))
    first = S.to_codec_json(schema)
    second = S.to_codec_json(schema)
    assert calls == [1]
    assert first.ast is second.ast
    assert S.decode_unknown_sync(second)(["x"]) == ("x",)


def test_a_derived_codec_is_its_own_json_codec():
    calls, link = _counted()
    derived = S.to_codec_json(_text(to_codec_json=link))
    assert S.to_codec_json(derived).ast is derived.ast
    assert calls == [1]


def test_a_string_tree_codec_is_derived_once_per_schema():
    calls, link = _counted()
    schema = _text(to_codec=link)
    assert S.to_codec_string_tree(schema).ast is S.to_codec_string_tree(schema).ast
    assert calls == [1]


def test_a_differently_annotated_copy_is_derived_on_its_own():
    calls, link = _counted()
    schema = _text(to_codec_json=link)
    S.to_codec_json(schema)
    S.to_codec_json(schema.annotate(description="text"))
    assert calls == [2]


def test_the_memo_does_not_keep_a_schema_alive():
    _, link = _counted()
    schema = S.Array(_text(to_codec_json=link))
    S.to_codec_json(schema)
    S.to_codec_string_tree(schema)
    held = weakref.ref(link)
    del schema, link
    gc.collect()
    assert held() is None


@testing.effect
def test_polling_a_workflow_derives_its_exit_codec_once():
    calls, link = _counted()
    wf = workflow.make(
        "PollMemo",
        payload=W.EMPTY,
        success=_text(to_codec_json=link),
        idempotency_key=lambda _: "one",
    )
    context = (
        yield from wf.to_layer(lambda _, __: fx.succeed("done"))
        .pipe(fx.layer.provide_merge(W.make_test_workflow_engine()))
        .build()
    )

    @fx.gen
    def run():
        execution_id = yield from wf.execute({}, discard=True)
        assert (yield from W.poll_until(wf, execution_id, Complete)) == Complete(
            Exit.succeed("done")
        )
        after_first = calls[0]
        for _ in range(5):
            yield from wf.poll(execution_id)
        assert calls[0] == after_first

    yield from run.pipe(fx.provide(context))
