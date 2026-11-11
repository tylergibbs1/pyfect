"""Tools a language model can call (Effect's ``Tool``).

A tool has a name, a parameters schema, a success schema and a failure
schema. Its type ``Tool[N_co, P_co, S, F_co, HE_co, R_co]`` keeps the name ``N_co``, the
decoded parameters ``P_co``, the success ``S``, the failure ``F_co``, the error a
handler raises to the caller ``HE_co`` (``F_co`` when ``failure_mode="error"``,
``Never`` when failures are returned to the model) and the services the
handler needs ``R_co`` (its ``dependencies``)::

    get_weather = tool.make(
        "GetWeather",
        description="The weather in a city",
        parameters=S.Struct(WeatherParams),
        success=S.Struct(Weather),
    )
    handler = get_weather.handler(lambda params, ctx: fx.succeed({...}))

``handler`` checks the function against the tool: a wrong success, failure
or an undeclared service is a type error. Handlers are given to a toolkit's
``to_layer``.

Provider-defined tools (``provider_defined``) run on the provider's side or
take provider arguments; dynamic tools (``dynamic``) take a raw JSON Schema
for their parameters.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Literal,
    LiteralString,
    Never,
    Self,
    TypedDict,
    TypeVar,
    cast,
    overload,
)

from pyfect import schema as S
from pyfect._json_text import parse as parse_json_text
from pyfect.ai.ai_error import AiError, AnyReason
from pyfect.ai.prompt import ToolModelOutputPart
from pyfect.context import Context, Reference, Tag
from pyfect.json_schema._model import JsonSchema

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.ai.prompt import Message

N_co = TypeVar("N_co", bound=LiteralString, covariant=True)
P_co = TypeVar("P_co", covariant=True)
S_co = TypeVar("S_co", covariant=True)
F_co = TypeVar("F_co", covariant=True)
HE_co = TypeVar("HE_co", covariant=True)
R_co = TypeVar("R_co", covariant=True)

type FailureMode = Literal["error", "return"]
type FailureOrigin = Literal["parameters", "handler", "result"]


@dataclass(frozen=True)
class NeedsApprovalContext:
    tool_call_id: str
    messages: Sequence[Message]


type NeedsApproval = bool | Callable[[Any, NeedsApprovalContext], bool | Effect[bool]]


@dataclass(frozen=True)
class HandlerContext[SS]:
    """What a handler gets besides its parameters: the call's id and
    ``preliminary``, which streams a progress value before the result."""

    tool_call_id: str | None
    preliminary: Callable[[SS], Effect[None]]


@dataclass(frozen=True)
class Handler(Generic[N_co]):
    """A tool's handler, made by ``Tool.handler``."""

    name: N_co
    tool_id: str
    run: Callable[[Any, HandlerContext[Any]], Effect[Any, Any, Any]]


type ToModelOutput = Callable[[Any], Sequence[ToolModelOutputPart]]
"""A tool's ``to_model_output``: a successful result to the parts the model
sees."""


@dataclass(frozen=True)
class Tool(Generic[N_co, P_co, S_co, F_co, HE_co, R_co]):
    """A tool the model can call (see the module docstring)."""

    name: N_co
    parameters_schema: S.Top
    success_schema: S.Top
    failure_schema: S.Top
    failure_mode: FailureMode = "error"
    description: str | None = None
    needs_approval: NeedsApproval | None = None
    annotations: Context[Any] = field(default_factory=Context.empty)
    to_model_output: ToModelOutput | None = None
    """Maps a successful result to what the model sees in place of the
    encoded result (images, files); the application still gets the typed
    result."""

    @property
    def id(self) -> str:
        return f"effect/ai/Tool/{self.name}"

    def handler[NN: LiteralString, PP, SS, FF, RR](
        self: Tool[NN, PP, SS, FF, Any, RR],
        fn: Callable[[PP, HandlerContext[SS]], Effect[SS, FF | AiError | AnyReason, RR]],
    ) -> Handler[NN]:
        """The handler ``fn`` for this tool; it may fail with the tool's
        failure, an ``AiError`` or an AI error reason."""
        return Handler(self.name, self.id, fn)

    def set_needs_approval(self, needs_approval: NeedsApproval) -> Self:
        return replace(self, needs_approval=needs_approval)

    def add_dependency[T](
        self, tag: type[Tag[Any]] | type[T]
    ) -> Tool[N_co, P_co, S_co, F_co, HE_co, R_co | T]:
        """The same tool, whose handler may also need ``tag``'s service."""
        return cast("Any", replace(self))

    def set_parameters[PP](
        self, schema: S.Codec[PP, Any, Any, Any]
    ) -> Tool[N_co, PP, S_co, F_co, HE_co, R_co]:
        return cast("Any", replace(self, parameters_schema=schema))

    def set_success[SS](
        self, schema: S.Codec[SS, Any, Any, Any]
    ) -> Tool[N_co, P_co, SS, F_co, HE_co, R_co]:
        return cast("Any", replace(self, success_schema=schema, to_model_output=None))

    def set_failure[FF](
        self, schema: S.Codec[FF, Any, Any, Any]
    ) -> Tool[N_co, P_co, S_co, FF, Any, R_co]:
        return cast("Any", replace(self, failure_schema=schema))

    def annotate[V](self, tag: type[Tag[V]], value: V) -> Self:
        return replace(self, annotations=self.annotations.add(tag, value))

    def annotate_merge(self, context: Context[Any]) -> Self:
        return replace(self, annotations=self.annotations.merge(context))


@dataclass(frozen=True)
class ProviderDefined(Tool[N_co, P_co, S_co, F_co, HE_co, R_co]):
    """A tool the provider defines (``provider_name`` on its side), with
    provider ``args``. ``requires_handler``: the toolkit must handle it."""

    provider_id: str = ""
    provider_name: str = ""
    args: object = None
    args_schema: S.Top = field(default_factory=lambda: S.Null)
    requires_handler: bool = False

    @property
    def id(self) -> str:
        return self.provider_id


@dataclass(frozen=True)
class Dynamic(Tool[N_co, P_co, S_co, F_co, HE_co, R_co]):
    """A tool whose parameters may be a raw JSON Schema (``json_schema``):
    its handler then gets the parameters undecoded."""

    json_schema: JsonSchema | None = None

    def set_parameters[PP](
        self, schema: S.Codec[PP, Any, Any, Any]
    ) -> Tool[N_co, PP, S_co, F_co, HE_co, R_co]:
        return cast("Any", replace(self, parameters_schema=schema, json_schema=None))


type AnyTool = Tool[Any, Any, Any, Any, Any, Any]


def is_user_defined(u: object) -> bool:
    return isinstance(u, Tool) and not isinstance(u, (ProviderDefined, Dynamic))


def is_provider_defined(u: object) -> bool:
    return isinstance(u, ProviderDefined)


def is_dynamic(u: object) -> bool:
    return isinstance(u, Dynamic)


EMPTY_PARAMS = S.Record(S.String, S.Never)
"""The parameters of a tool that takes none (Effect's ``EmptyParams``)."""


class ExecutionFailureDict(TypedDict):
    type: Literal["execution-denied", "execution-interrupted"]
    reason: str


EXECUTION_FAILURE: S.Bottom[ExecutionFailureDict] = cast(
    "Any", S.Struct(ExecutionFailureDict).annotate(identifier="ToolExecutionFailure")
)
"""A tool call that never ran: the user denied it, or the response ended
first (Effect's ``ExecutionFailure``)."""


def failure_result_schema(tool: AnyTool) -> S.Top:
    """What a tool's failed result can be: an ``AiError``, the tool's
    failure or an ``EXECUTION_FAILURE``."""
    return S.Union(cast("Any", AiError), tool.failure_schema, EXECUTION_FAILURE)


# Constructors ------------------------------------------------------------------------


@overload
def make[NN: LiteralString, PP = dict[str, Never], SS = None, FF = Never, RR = Never](
    name: NN,
    *,
    description: str | None = None,
    parameters: S.Codec[PP, Any, Any, Any] | None = None,
    success: S.Codec[SS, Any, Any, Any] | None = None,
    failure: S.Codec[FF, Any, Any, Any] | None = None,
    failure_mode: Literal["error"] = "error",
    dependencies: Sequence[type[RR]] = (),
    needs_approval: NeedsApproval | None = None,
    to_model_output: Callable[[SS], Sequence[ToolModelOutputPart]] | None = None,
) -> Tool[NN, PP, SS, FF, FF, RR]: ...
@overload
def make[NN: LiteralString, PP = dict[str, Never], SS = None, FF = Never, RR = Never](
    name: NN,
    *,
    description: str | None = None,
    parameters: S.Codec[PP, Any, Any, Any] | None = None,
    success: S.Codec[SS, Any, Any, Any] | None = None,
    failure: S.Codec[FF, Any, Any, Any] | None = None,
    failure_mode: Literal["return"],
    dependencies: Sequence[type[RR]] = (),
    needs_approval: NeedsApproval | None = None,
    to_model_output: Callable[[SS], Sequence[ToolModelOutputPart]] | None = None,
) -> Tool[NN, PP, SS, FF, Never, RR]: ...
def make(
    name: str,
    *,
    description: str | None = None,
    parameters: S.Top | None = None,
    success: S.Top | None = None,
    failure: S.Top | None = None,
    failure_mode: FailureMode = "error",
    dependencies: Sequence[type] = (),
    needs_approval: NeedsApproval | None = None,
    to_model_output: ToModelOutput | None = None,
) -> Tool[Any, Any, Any, Any, Any, Any]:
    """A tool the toolkit handles. Its parameters default to none, its
    success to ``None`` and its failure to ``Never``. ``to_model_output``
    maps a successful result to the parts the model sees in its place."""
    del dependencies
    return Tool[Any, Any, Any, Any, Any, Any](
        name=name,
        parameters_schema=EMPTY_PARAMS if parameters is None else parameters,
        success_schema=S.Null if success is None else success,
        failure_schema=S.Never if failure is None else failure,
        failure_mode=failure_mode,
        description=description,
        needs_approval=needs_approval,
        to_model_output=to_model_output,
    )


@overload
def dynamic[NN: LiteralString, PP = object, SS = object, FF = Never](
    name: NN,
    *,
    description: str | None = None,
    parameters: S.Codec[PP, Any, Any, Any] | None = None,
    success: S.Codec[SS, Any, Any, Any] | None = None,
    failure: S.Codec[FF, Any, Any, Any] | None = None,
    failure_mode: Literal["error"] = "error",
    needs_approval: NeedsApproval | None = None,
    to_model_output: Callable[[SS], Sequence[ToolModelOutputPart]] | None = None,
) -> Dynamic[NN, PP, SS, FF, FF, Never]: ...
@overload
def dynamic[NN: LiteralString, SS = object, FF = Never](
    name: NN,
    *,
    description: str | None = None,
    parameters: JsonSchema,
    success: S.Codec[SS, Any, Any, Any] | None = None,
    failure: S.Codec[FF, Any, Any, Any] | None = None,
    failure_mode: Literal["error"] = "error",
    needs_approval: NeedsApproval | None = None,
    to_model_output: Callable[[SS], Sequence[ToolModelOutputPart]] | None = None,
) -> Dynamic[NN, object, SS, FF, FF, Never]: ...
@overload
def dynamic[NN: LiteralString, PP = object, SS = object, FF = Never](
    name: NN,
    *,
    description: str | None = None,
    parameters: S.Codec[PP, Any, Any, Any] | JsonSchema | None = None,
    success: S.Codec[SS, Any, Any, Any] | None = None,
    failure: S.Codec[FF, Any, Any, Any] | None = None,
    failure_mode: Literal["return"],
    needs_approval: NeedsApproval | None = None,
    to_model_output: Callable[[SS], Sequence[ToolModelOutputPart]] | None = None,
) -> Dynamic[NN, PP, SS, FF, Never, Never]: ...
def dynamic(
    name: str,
    *,
    description: str | None = None,
    parameters: S.Top | JsonSchema | None = None,
    success: S.Top | None = None,
    failure: S.Top | None = None,
    failure_mode: FailureMode = "error",
    needs_approval: NeedsApproval | None = None,
    to_model_output: ToModelOutput | None = None,
) -> Dynamic[Any, Any, Any, Any, Any, Any]:
    """A tool whose parameters are a schema or a raw JSON Schema; its
    success defaults to any value."""
    is_schema = parameters is not None and hasattr(parameters, "__codec__")
    return Dynamic[Any, Any, Any, Any, Any, Any](
        name=name,
        parameters_schema=cast("S.Top", parameters) if is_schema else S.Unknown,
        success_schema=S.Unknown if success is None else success,
        failure_schema=S.Never if failure is None else failure,
        failure_mode=failure_mode,
        description=description,
        needs_approval=needs_approval,
        to_model_output=to_model_output,
        json_schema=None if is_schema or parameters is None else cast("JsonSchema", parameters),
    )


def provider_defined[NN: LiteralString, PP = None, SS = None, FF = Never](
    *,
    id: str,
    custom_name: NN,
    provider_name: str,
    args: S.Top | None = None,
    requires_handler: bool = False,
    parameters: S.Codec[PP, Any, Any, Any] | None = None,
    success: S.Codec[SS, Any, Any, Any] | None = None,
    failure: S.Codec[FF, Any, Any, Any] | None = None,
) -> Callable[..., ProviderDefined[NN, PP, SS, FF, FF, Never]]:
    """A provider-defined tool's constructor: call it with the tool's
    arguments (encoded) and, when ``requires_handler``, ``failure_mode``."""
    parameters_schema: S.Top = S.Null if parameters is None else parameters
    success_schema: S.Top = S.Null if success is None else success
    failure_schema: S.Top = S.Never if failure is None else failure

    def construct(
        args_value: Mapping[str, object] | None = None, /, **kwargs: object
    ) -> ProviderDefined[NN, PP, SS, FF, FF, Never]:
        values = {**(args_value or {}), **kwargs}
        mode = cast("FailureMode", values.pop("failure_mode", "error"))
        return ProviderDefined(
            name=custom_name,
            parameters_schema=parameters_schema,
            success_schema=success_schema,
            failure_schema=failure_schema,
            failure_mode=mode,
            provider_id=id,
            provider_name=provider_name,
            args=values,
            args_schema=S.Null if args is None else args,
            requires_handler=requires_handler,
        )

    return construct


# Names, descriptions and JSON Schemas ---------------------------------------------------


class NameMapper:
    """Maps provider-defined tools' custom names to their provider names
    and back; other names map to themselves."""

    def __init__(self, tools: Sequence[AnyTool]) -> None:
        self._to_provider: dict[str, str] = {}
        self._to_custom: dict[str, str] = {}
        for tool in tools:
            if isinstance(tool, ProviderDefined):
                self._to_provider[tool.name] = tool.provider_name
                self._to_custom[tool.provider_name] = tool.name

    @property
    def custom_names(self) -> tuple[str, ...]:
        return tuple(self._to_provider)

    @property
    def provider_names(self) -> tuple[str, ...]:
        return tuple(self._to_custom)

    def get_custom_name(self, provider_name: str) -> str:
        return self._to_custom.get(provider_name, provider_name)

    def get_provider_name(self, custom_name: str) -> str:
        return self._to_provider.get(custom_name, custom_name)


def get_description(tool: AnyTool) -> str | None:
    """The tool's description, or its parameters schema's."""
    if tool.description is not None:
        return tool.description
    annotations = tool.parameters_schema.__codec__().ast.annotations or {}
    description = annotations.get("description")
    return description if isinstance(description, str) else None


type CodecTransformer = Callable[[S.Top], tuple[S.Top, JsonSchema]]
"""A provider's rewrite of a schema: the codec to decode the model's output
with and the JSON Schema to send (Effect's ``CodecTransformer``)."""


def get_json_schema(tool: AnyTool, *, transformer: CodecTransformer | None = None) -> JsonSchema:
    """The JSON Schema of the tool's parameters."""
    if isinstance(tool, Dynamic) and tool.json_schema is not None:
        return tool.json_schema
    return get_json_schema_from_schema(tool.parameters_schema, transformer=transformer)


def get_json_schema_from_schema(
    schema: S.Top, *, transformer: CodecTransformer | None = None
) -> JsonSchema:
    """``schema``'s JSON Schema, its definitions under ``$defs``."""
    if transformer is not None:
        return transformer(schema)[1]
    document = S.to_json_schema_document(schema)
    result = dict(document.schema)
    if document.definitions:
        result["$defs"] = dict(document.definitions)
    return result


# Annotations ---------------------------------------------------------------------------


class Title(Tag[str], key="effect/ai/Tool/Title"):
    """A human-readable title."""


class Meta(Tag[dict[str, object]], key="effect/ai/Tool/Meta"):
    """Free-form metadata."""


class Readonly(Reference[bool], key="effect/ai/Tool/Readonly"):
    @classmethod
    def default(cls) -> bool:
        return False


class Destructive(Reference[bool], key="effect/ai/Tool/Destructive"):
    @classmethod
    def default(cls) -> bool:
        return True


class Idempotent(Reference[bool], key="effect/ai/Tool/Idempotent"):
    @classmethod
    def default(cls) -> bool:
        return False


class OpenWorld(Reference[bool], key="effect/ai/Tool/OpenWorld"):
    @classmethod
    def default(cls) -> bool:
        return True


class Strict(Reference[bool | None], key="effect/ai/Tool/Strict"):
    @classmethod
    def default(cls) -> bool | None:
        return None


def get_strict_mode(tool: AnyTool) -> bool | None:
    return tool.annotations.get_unsafe(Strict)


# Secure JSON --------------------------------------------------------------------------

# ``json.loads`` decodes Unicode escapes (``"\u005f_proto__"``), so any ``\u`` triggers the scan.
_SUSPECT = re.compile(r'"(__proto__|constructor)"\s*:|\\u')


def unsafe_secure_json_parse(text: str) -> object:
    """``json.loads``, refusing an object with a ``__proto__`` key or a
    ``constructor`` object holding ``prototype`` (raises ``ValueError``):
    JavaScript would let such keys reach a prototype."""
    value: object = parse_json_text(text)
    if _SUSPECT.search(text) is None:
        return value
    pending: list[object] = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            items = cast("dict[str, object]", node)
            if "__proto__" in items:
                raise ValueError("Object contains forbidden prototype property")
            constructor = items.get("constructor")
            if isinstance(constructor, dict) and "prototype" in constructor:
                raise ValueError("Object contains forbidden prototype property")
            pending.extend(items.values())
        elif isinstance(node, list):
            pending.extend(cast("list[object]", node))
    return value


__all__ = [
    "EMPTY_PARAMS",
    "EXECUTION_FAILURE",
    "AnyTool",
    "CodecTransformer",
    "Destructive",
    "Dynamic",
    "ExecutionFailureDict",
    "FailureMode",
    "FailureOrigin",
    "Handler",
    "HandlerContext",
    "Idempotent",
    "Meta",
    "NameMapper",
    "NeedsApproval",
    "NeedsApprovalContext",
    "OpenWorld",
    "ProviderDefined",
    "Readonly",
    "Strict",
    "Title",
    "ToModelOutput",
    "Tool",
    "dynamic",
    "failure_result_schema",
    "get_description",
    "get_json_schema",
    "get_json_schema_from_schema",
    "get_strict_mode",
    "is_dynamic",
    "is_provider_defined",
    "is_user_defined",
    "make",
    "provider_defined",
    "unsafe_secure_json_parse",
]
