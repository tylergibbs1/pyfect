"""``HandlerHook``: what ``pyfect.ai.durable`` puts around each tool call a language
model's response makes, to run it as a workflow activity. ``handle`` is how the language
model runs a call: through the hook in context, else straight to the toolkit."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pyfect.context import Reference

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.ai.toolkit import HandlerResult, WithHandler
    from pyfect.stream import Stream

type Handled = Effect[Stream[HandlerResult, Any, Any], Any, Any]
"""A call's results, as ``WithHandler.handle`` gives them."""

type Hook = Callable[[WithHandler[Any, Any, Any, Any], str, object, str], Handled]
"""Gets the toolkit, the tool's name, the parameters as the model sent them and the
call's id, and runs the call."""


class HandlerHook(Reference[Hook | None], key="pyfect/ai/Toolkit/HandlerHook"):
    """Runs each tool call a response makes; ``None`` (the toolkit's ``handle``) by
    default."""

    @classmethod
    def default(cls) -> Hook | None:
        return None


def handle_call(
    kit: WithHandler[Any, Any, Any, Any], name: str, params: object, tool_call_id: str
) -> Handled:
    """``kit.handle(name, params, tool_call_id)``, through the hook in context."""
    return HandlerHook().flat_map(
        lambda hook: (
            kit.handle(name, params, tool_call_id)
            if hook is None
            else hook(kit, name, params, tool_call_id)
        )
    )
