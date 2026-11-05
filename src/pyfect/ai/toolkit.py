"""Groups of tools and their handlers (Effect's ``Toolkit``).

A toolkit is an effect: run, it reads its tools' handlers from the context
and gives a ``WithHandler``, which a language model uses to run the tool
calls it makes::

    toolkit = Toolkit.make(get_weather, get_time)
    handlers = toolkit.to_layer(
        get_weather.handler(lambda params, ctx: fx.succeed(...)),
        get_time.handler(lambda params, ctx: fx.succeed(...)),
    )
    response = language_model.generate_text("...", toolkit=toolkit).pipe(
        fx.provide(handlers)
    )

``Toolkit[N_co, RP_co, HE_co, R_co]`` keeps the tool names ``N_co``, the union ``RP_co`` of
each tool's ``ToolResultSuccess`` and ``ToolResultFailure``, the errors its
handlers raise ``HE_co`` and the services they need ``R_co``; the toolkit itself
needs ``Handlers[N_co]``, which ``to_layer`` provides.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Generic, LiteralString, Never, TypeVar, cast, final, overload

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai import ai_error as AiErr
from pyfect.ai.ai_error import AiError
from pyfect.ai.response import ToolResultFailure, ToolResultSuccess
from pyfect.ai.tool import (
    AnyTool,
    FailureOrigin,
    Handler,
    HandlerContext,
    Tool,
    failure_result_schema,
)
from pyfect.cause import Cause, Fail, from_reasons
from pyfect.context import Context, MissingServiceError, Reference, ServiceMarker, Tag
from pyfect.exit import Failure, Success
from pyfect.layer import Layer, effect_context
from pyfect.queue import Queue
from pyfect.schema import SchemaError
from pyfect.stream import Stream
from pyfect.stream import _constructors as StreamC
from pyfect.stream import _sources as StreamSources

if TYPE_CHECKING:
    from pyfect._effect_base import Step
    from pyfect._fiber import Fiber

N_co = TypeVar("N_co", bound=LiteralString, covariant=True)
RP_co = TypeVar("RP_co", covariant=True)
HE_co = TypeVar("HE_co", covariant=True)
R_co = TypeVar("R_co", covariant=True)


class Handlers(ServiceMarker, Generic[N_co]):
    """The requirement of a toolkit whose tools are named ``N_co``: their
    handlers, which ``Toolkit.to_layer`` provides. A marker, never built."""


class FailureOriginAnnotation(Reference[FailureOrigin], key="effect/ai/Toolkit/FailureOrigin"):
    """Where a tool failure came from, annotated on the failure's cause:
    ``"parameters"``, ``"handler"`` or ``"result"`` (an invalid result)."""

    @classmethod
    def default(cls) -> FailureOrigin:
        return "result"


class PreliminaryBuffer(Reference[int | None], key="effect/ai/Toolkit/PreliminaryBuffer"):
    """How many preliminary results a handler may get ahead of its
    consumer; ``None`` (the default) is unbounded."""

    @classmethod
    def default(cls) -> int | None:
        return None


@dataclass(frozen=True)
class _Registered:
    handler: Handler[Any]
    context: Context[Any]


_handler_tags: dict[str, type[Tag[_Registered]]] = {}


def map_handler_contexts(
    toolkit: Toolkit[Any, Any, Any, Any],
    context: Context[Any],
    f: Callable[[Context[Any]], Context[Any]],
) -> Context[Any]:
    """``context`` with ``f`` applied to the context each of ``toolkit``'s
    handlers kept from where its layer was built."""
    out = context
    for tool in toolkit.tools.values():
        tag = _handler_tag(tool.id)
        found, registered = out.lookup(tag)
        if found:
            out = out.add(tag, replace(registered, context=f(registered.context)))
    return out


def _handler_tag(tool_id: str) -> type[Tag[_Registered]]:
    tag = _handler_tags.get(tool_id)
    if tag is None:
        tag = cast("type[Tag[_Registered]]", type(f"Handler[{tool_id}]", (Tag,), {}, key=tool_id))
        _handler_tags[tool_id] = tag
    return tag


@dataclass(frozen=True)
class HandlerResult:
    """One output of a tool call: the result, what the model sees of it
    (``encoded_result``), whether it is a failure (and its origin) and
    whether it is a preliminary progress value."""

    result: object
    encoded_result: object
    is_failure: bool
    preliminary: bool
    failure_origin: FailureOrigin | None = None


def _make_error(name: str, reason: AiErr.AnyReason) -> AiError:
    return AiError(module="Toolkit", method=f"{name}.handle", reason=reason)


@dataclass(frozen=True)
class _Output:
    result: object
    is_failure: bool
    preliminary: bool
    failure_origin: FailureOrigin | None = None


def _origin(error: object) -> FailureOrigin:
    return "result" if isinstance(error, SchemaError) else "handler"


@dataclass(frozen=True)
class WithHandler(Generic[N_co, RP_co, HE_co, R_co]):
    """A toolkit with its handlers: ``handle`` runs a tool call."""

    tools: Mapping[str, AnyTool]
    services: Context[Any] = field(repr=False)

    def handle(
        self,
        name: str,
        params: object,
        tool_call_id: str | None = None,
        options: S.ParseOptions | None = None,
    ) -> Effect[Stream[HandlerResult, HE_co | AiError, R_co], AiError, R_co]:
        """The results of calling the tool ``name`` with ``params`` (as the
        model sent them, decoded with ``options``): preliminary values, then
        the final one. Invalid parameters, a handler failure or an invalid
        result fail the stream in ``"error"`` mode and are a failed result in
        ``"return"`` mode."""
        return cast("Any", _handle(self, name, params, tool_call_id, options or {}))


def _handle(
    kit: WithHandler[Any, Any, Any, Any],
    name: str,
    params: object,
    tool_call_id: str | None,
    options: S.ParseOptions,
) -> Effect[Stream[HandlerResult, Any, Any], AiError, Any]:
    tool = kit.tools.get(name)
    annotate = fx.annotate_current_span({"tool": name, "parameters": params})
    if tool is None:
        error = _make_error(
            name, AiErr.ToolNotFoundError(tool_name=name, available_tools=tuple(kit.tools))
        )
        return annotate.and_then(fx.fail(error))
    found, registered_value = kit.services.lookup(_handler_tag(tool.id))
    if not found:
        missing = MissingServiceError(f"Service {tool.id} was not provided (a tool handler)")
        return annotate.and_then(fx.die(missing))
    registered = cast("_Registered", registered_value)
    encode_success: Callable[[object], Effect[object, SchemaError]] = cast(
        "Any", S.encode_unknown_effect(tool.success_schema)
    )
    encode_failure: Callable[[object], Effect[object, SchemaError]] = cast(
        "Any", S.encode_unknown_effect(failure_result_schema(tool))
    )

    def encode(output: _Output) -> Effect[HandlerResult, AiError]:
        encoder = encode_failure if output.is_failure else encode_success
        return (
            encoder(output.result)
            .map(
                lambda encoded: HandlerResult(
                    output.result,
                    encoded,
                    output.is_failure,
                    output.preliminary,
                    output.failure_origin,
                )
            )
            .map_error(
                lambda error: _make_error(
                    name,
                    AiErr.ToolResultEncodingError(
                        tool_name=name,
                        tool_result=output.result,
                        description=AiErr.describe_schema_error(error),
                    ),
                )
            )
        )

    def invalid_params(error: SchemaError) -> Effect[Stream[HandlerResult, Any, Any], AiError]:
        failure = _make_error(
            name,
            AiErr.ToolParameterValidationError(
                tool_name=name, description=AiErr.describe_schema_error(error)
            ),
        )
        if tool.failure_mode == "error":
            origin = Context.make(FailureOriginAnnotation, "parameters")
            return fx.fail_cause(Cause((Fail(failure),)).annotate(origin))
        return fx.succeed(StreamC.from_effect(encode(_Output(failure, True, False, "parameters"))))

    def normalize(error: object) -> object:
        if isinstance(error, SchemaError):
            return _make_error(
                name,
                AiErr.InvalidToolResultError(
                    tool_name=name,
                    description="Tool handler returned invalid result: "
                    + AiErr.describe_schema_error(error),
                ),
            )
        if AiErr.is_ai_error_reason(error):
            return _make_error(name, cast("AiErr.AnyReason", error))
        return error

    def run(decoded: object) -> Effect[Stream[HandlerResult, Any, Any], Never, Any]:
        def with_capacity(
            capacity: int | None,
        ) -> Effect[Stream[HandlerResult, Any, Any], Never, Any]:
            if capacity is not None and capacity <= 0:
                message = f"PreliminaryBuffer must be a positive integer, got {capacity}"
                return fx.die(ValueError(f'Tool "{name}": {message}'))
            make_queue = (
                Queue[_Output, Any].unbounded()
                if capacity is None
                else Queue[_Output, Any].bounded(capacity)
            )
            return make_queue.flat_map(start)

        def start(
            queue: Queue[_Output, Any],
        ) -> Effect[Stream[HandlerResult, Any, Any], Never, Any]:
            context = HandlerContext[Any](
                tool_call_id,
                lambda value: queue.offer(_Output(value, False, True)).as_(None),
            )
            body = fx.suspend(lambda: registered.handler.run(decoded, context)).flat_map(
                lambda result: queue.offer(_Output(result, False, False))
            )
            provided = fx.context().flat_map(
                lambda current: body.pipe(fx.provide_context(registered.context.merge(current)))
            )
            worker = provided.match_cause_effect(
                on_failure=queue.fail_cause,
                on_success=lambda _: queue.end(),
            )
            return worker.fork().map(lambda fiber: results(queue, fiber))

        return PreliminaryBuffer().flat_map(with_capacity)

    def results(queue: Queue[_Output, Any], fiber: Any) -> Stream[HandlerResult, Any, Any]:
        source: Stream[_Output, Any, Any] = StreamSources.from_queue(queue)
        if tool.failure_mode == "error":

            def reannotate(cause: Cause[Any]) -> Stream[_Output, Any]:
                reasons = [
                    reason.annotate(
                        Context.make(FailureOriginAnnotation, _origin(reason.error)), overwrite=True
                    )
                    if isinstance(reason, Fail)
                    else reason
                    for reason in cause.reasons
                ]
                return StreamC.fail_cause(from_reasons(reasons).map(normalize))

            source = source.catch_cause(reannotate)
        else:
            source = source.catch_all(
                lambda error: StreamC.succeed(
                    _Output(normalize(error), True, False, _origin(error))
                )
            )
        return source.map_effect(encode).ensuring(fiber.interrupt())

    decode = (
        S.decode_unknown_effect(tool.parameters_schema, **options)(params)
        .exit()
        .flat_map(
            lambda exit: (
                run(exit.value)
                if isinstance(exit, Success)
                else _params_failure(cast("Failure[Any]", exit), invalid_params)
            )
        )
    )
    return annotate.and_then(decode)


def _params_failure(
    exit: Failure[Any], on_schema: Callable[[SchemaError], Effect[Any, Any, Any]]
) -> Effect[Any, Any, Any]:
    found = exit.cause.find_error()
    error = getattr(found, "value", None)
    if isinstance(error, SchemaError):
        return on_schema(error)
    return fx.fail_cause(exit.cause)


@final
class Toolkit(Effect[WithHandler[N_co, RP_co, HE_co, R_co], Never, Handlers[N_co]]):
    """Tools by name. Run, it gives them with their handlers."""

    __slots__ = ("tools",)

    def __init__(self, tools: Mapping[str, AnyTool]) -> None:
        self.tools: Mapping[str, AnyTool] = dict(tools)

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        tools = self.tools
        return fx.context().map(lambda services: WithHandler[Any, Any, Any, Any](tools, services))

    def __repr__(self) -> str:
        return f"Toolkit({', '.join(self.tools)})"

    def to_json(self) -> dict[str, object]:
        return {"_id": "effect/ai/Toolkit", "tools": [tool.name for tool in self.tools.values()]}

    @overload
    def to_handlers(self, *handlers: Handler[Any]) -> Effect[Context[Handlers[N_co]]]: ...
    @overload
    def to_handlers[EE, RR](
        self, handlers: Effect[Iterable[Handler[Any]], EE, RR], /
    ) -> Effect[Context[Handlers[N_co]], EE, RR]: ...
    def to_handlers(self, *handlers: Any) -> Effect[Context[Any], Any, Any]:
        """The context holding ``handlers`` (or the ones an effect makes).
        Every tool needs one, except provider-defined tools that do not
        require a handler (a missing one raises ``ValueError``)."""
        build: Effect[Iterable[Handler[Any]], Any, Any] = (
            cast("Effect[Iterable[Handler[Any]], Any, Any]", handlers[0])
            if len(handlers) == 1 and isinstance(handlers[0], Effect)
            else fx.succeed(cast("tuple[Handler[Any], ...]", handlers))
        )
        return fx.context().flat_map(
            lambda services: build.flat_map(
                lambda made: fx.sync(lambda: self._build_context(made, services))
            )
        )

    def _build_context(
        self, handlers: Iterable[Handler[Any]], services: Context[Any]
    ) -> Context[Any]:
        by_name: dict[str, Handler[Any]] = {handler.name: handler for handler in handlers}
        registered: dict[type[Tag[Any]], object] = {}
        for name, tool in self.tools.items():
            handler = by_name.get(name)
            if handler is None:
                if getattr(tool, "requires_handler", True):
                    raise ValueError(f"Toolkit: no handler for the tool {name!r}")
                handler = Handler[Any](name, tool.id, _no_handler(name))
            registered[_handler_tag(tool.id)] = _Registered(handler, services)
        return Context(registered)

    @overload
    def to_layer(self, *handlers: Handler[Any]) -> Layer[Handlers[N_co]]: ...
    @overload
    def to_layer[EE, RR](
        self, handlers: Effect[Iterable[Handler[Any]], EE, RR], /
    ) -> Layer[Handlers[N_co], EE, RR]: ...
    def to_layer(self, *handlers: Any) -> Layer[Any, Any, Any]:
        """A layer providing ``handlers`` (see ``to_handlers``)."""
        return effect_context(cast("Any", self.to_handlers(*handlers)))


def _no_handler(name: str) -> Callable[[Any, HandlerContext[Any]], Effect[Any, Any]]:
    def run(_: Any, __: HandlerContext[Any]) -> Effect[Any, Any]:
        return fx.die(ValueError(f"Toolkit: the provider-defined tool {name!r} has no handler"))

    return run


type AnyToolkit = Toolkit[Any, Any, Any, Any]

N1 = TypeVar("N1", bound=LiteralString)
N2 = TypeVar("N2", bound=LiteralString)
N3 = TypeVar("N3", bound=LiteralString)
N4 = TypeVar("N4", bound=LiteralString)
S1 = TypeVar("S1")
S2 = TypeVar("S2")
S3 = TypeVar("S3")
S4 = TypeVar("S4")
F1 = TypeVar("F1")
F2 = TypeVar("F2")
F3 = TypeVar("F3")
F4 = TypeVar("F4")
EE = TypeVar("EE")
RR = TypeVar("RR")

type _Results[NN: str, SS, FF] = ToolResultSuccess[NN, SS] | ToolResultFailure[NN, FF | AiError]


@overload
def make() -> Toolkit[Never, Never, Never, Never]: ...
@overload
def make(t1: Tool[N1, Any, S1, F1, EE, RR], /) -> Toolkit[N1, _Results[N1, S1, F1], EE, RR]: ...
@overload
def make(
    t1: Tool[N1, Any, S1, F1, EE, RR], t2: Tool[N2, Any, S2, F2, EE, RR], /
) -> Toolkit[N1 | N2, _Results[N1, S1, F1] | _Results[N2, S2, F2], EE, RR]: ...
@overload
def make(
    t1: Tool[N1, Any, S1, F1, EE, RR],
    t2: Tool[N2, Any, S2, F2, EE, RR],
    t3: Tool[N3, Any, S3, F3, EE, RR],
    /,
) -> Toolkit[
    N1 | N2 | N3, _Results[N1, S1, F1] | _Results[N2, S2, F2] | _Results[N3, S3, F3], EE, RR
]: ...
@overload
def make(
    t1: Tool[N1, Any, S1, F1, EE, RR],
    t2: Tool[N2, Any, S2, F2, EE, RR],
    t3: Tool[N3, Any, S3, F3, EE, RR],
    t4: Tool[N4, Any, S4, F4, EE, RR],
    /,
) -> Toolkit[
    N1 | N2 | N3 | N4,
    _Results[N1, S1, F1] | _Results[N2, S2, F2] | _Results[N3, S3, F3] | _Results[N4, S4, F4],
    EE,
    RR,
]: ...
@overload
def make(*tools: AnyTool) -> AnyToolkit: ...
def make(*tools: AnyTool) -> AnyToolkit:
    """A toolkit of ``tools``, by name (a later tool replaces an earlier
    one of the same name)."""
    return Toolkit({tool.name: tool for tool in tools})


empty: Toolkit[Never, Never, Never, Never] = Toolkit({})
"""The toolkit with no tools."""

RP1 = TypeVar("RP1")
RP2 = TypeVar("RP2")


@overload
def merge(
    k1: Toolkit[N1, RP1, EE, RR], k2: Toolkit[N2, RP2, EE, RR], /
) -> Toolkit[N1 | N2, RP1 | RP2, EE, RR]: ...
@overload
def merge(*toolkits: AnyToolkit) -> AnyToolkit: ...
def merge(*toolkits: AnyToolkit) -> AnyToolkit:
    """One toolkit of every toolkit's tools (a later one wins a name)."""
    tools: dict[str, AnyTool] = {}
    for toolkit in toolkits:
        tools.update(toolkit.tools)
    return Toolkit(tools)


__all__ = [
    "AiError",
    "AnyToolkit",
    "FailureOriginAnnotation",
    "HandlerResult",
    "Handlers",
    "PreliminaryBuffer",
    "Toolkit",
    "WithHandler",
    "empty",
    "make",
    "map_handler_contexts",
    "merge",
]
