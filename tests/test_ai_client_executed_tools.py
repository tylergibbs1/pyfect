"""Client-executed tools (``execution="client"``) need no handler: a toolkit's layer is
built without one, and handling a call to one is a defect, as in Effect's
``Toolkit``."""

from __future__ import annotations

from typing import TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.cause import Die
from pyfect.exit import Failure


class Question(TypedDict):
    question: str


Ask = T.make("Ask", parameters=S.Struct(Question), success=S.Boolean, execution="client")
Confirm = T.dynamic("Confirm", parameters={"type": "object", "properties": {}}, execution="client")
Lookup = T.make("Lookup", success=S.String)


def test_only_server_tools_require_a_handler() -> None:
    assert [T.requires_handler(tool) for tool in (Ask, Confirm, Lookup)] == [False, False, True]
    assert [T.is_client_executed(tool) for tool in (Ask, Confirm, Lookup)] == [True, True, False]
    # Combinators keep the execution mode.
    assert T.is_client_executed(Ask.set_success(S.Number).set_needs_approval(True))


def test_a_toolkit_layer_needs_handlers_for_server_tools_only() -> None:
    toolkit = K.make(Ask, Confirm, Lookup)
    handlers = toolkit.to_layer(Lookup.handler(lambda _, __: fx.succeed("value")))
    kit = fx.run_sync(toolkit.pipe(fx.provide(handlers)))
    assert set(kit.tools) == {"Ask", "Confirm", "Lookup"}
    with pytest.raises(ValueError, match="no handler for the tool 'Lookup'"):
        fx.run_sync(toolkit.pipe(fx.provide(toolkit.to_layer())))


def test_handling_a_client_executed_tool_call_is_a_defect() -> None:
    toolkit = K.make(Ask, Lookup)
    handlers = toolkit.to_layer(Lookup.handler(lambda _, __: fx.succeed("value")))
    handled = toolkit.flat_map(lambda kit: kit.handle("Ask", {"question": "Proceed?"}))
    exit = fx.run_sync_exit(handled.pipe(fx.provide(handlers)))
    assert isinstance(exit, Failure)
    [reason] = exit.cause.reasons
    assert isinstance(reason, Die)
    assert str(reason.defect) == 'Tool "Ask" is executed by the client and has no handler'
