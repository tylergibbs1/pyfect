"""The Standard Schema interface in Python form (Effect's
``toStandardSchemaV1`` / ``toStandardJSONSchemaV1``).

Libraries meet at a ``~standard`` property; here it is the ``~standard``
attribute (``getattr(adapted, "~standard")``) of an adapter that wraps a
schema, typed as ``__standard__``. The adapter
is still the schema: it decodes like it (``__codec__``), reads and calls
through to it (``Item``, a class's constructor, ``isinstance`` against a
schema class, subclassing it), and keeps attributes written to it local.
``~standard`` holds ``version`` (1), ``vendor`` (``"pyfect"``) and
``validate`` (``to_standard_schema_v1``) or ``json_schema``
(``to_standard_json_schema_v1``, whose ``input`` / ``output`` take the
spec's ``{"target": ...}`` options); adapting an adapter keeps the members
it already has.

``validate(value, options=None)`` (Effect ignores the options too) gives
``{"value": ...}`` or ``{"issues": [{"message", "path"}, ...]}``, decoding
with ``errors="all"`` unless ``parse_options`` says otherwise,
synchronously when the decoding ran without waiting, else an awaitable of
that result (Effect's ``Promise``). A defect gives one issue, the cause's
text, without a path.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MethodType
from typing import (
    Any,
    Final,
    Generic,
    Literal,
    Never,
    NotRequired,
    Protocol,
    ReadOnly,
    TypedDict,
    TypeVar,
    cast,
)

from pyfect._fiber import Fiber
from pyfect._root import new_root
from pyfect.context import Context
from pyfect.exit import Exit, Success
from pyfect.json_schema import (
    META_SCHEMA_URI_DRAFT_07,
    META_SCHEMA_URI_DRAFT_2020_12,
    JsonSchema,
    to_document_draft_07,
)
from pyfect.run import drive
from pyfect.scheduler import SyncScheduler
from pyfect.schema import ast as ast_module
from pyfect.schema._jsonschema import to_json_schema_document
from pyfect.schema._options import ParseOptions
from pyfect.schema._parse import decode_unknown_effect
from pyfect.schema._primitives import Finite, String
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema.issue import CheckHook, LeafHook, make_formatter_standard_schema_v1
from pyfect.schema.issue import Path as IssuePath

T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)

type Target = Literal["draft-2020-12", "draft-07"]


class SuccessResult[A](TypedDict):
    """``StandardSchemaV1.SuccessResult``."""

    value: A


class Issue(TypedDict):
    """``StandardSchemaV1.Issue``: a message and, below the root, a path."""

    message: ReadOnly[str]
    path: ReadOnly[NotRequired[IssuePath]]


class FailureResult(TypedDict):
    """``StandardSchemaV1.FailureResult``."""

    issues: Sequence[Issue]


type Result[A] = SuccessResult[A] | FailureResult


class ValidateOptions(TypedDict):
    """``StandardSchemaV1.Options``."""

    libraryOptions: NotRequired[Mapping[str, object]]


class Validate[A](Protocol):
    """``StandardSchemaV1.Props.validate``."""

    def __call__(
        self, value: object, options: ValidateOptions | None = None, /
    ) -> Result[A] | Awaitable[Result[A]]: ...


class JsonSchemaOptions(TypedDict):
    """``StandardJSONSchemaV1.Options``: the dialect to write."""

    target: Target
    libraryOptions: NotRequired[Mapping[str, object]]


def _failure_result() -> Bottom[FailureResult, FailureResult]:
    key = ast_module.Union((Finite.ast, String.ast))
    segment = ast_module.Union((key, ast_module.struct({"key": key})))
    issue = ast_module.Objects(
        (
            ast_module.PropertySignature("message", String.ast, False),
            ast_module.PropertySignature("path", ast_module.Arrays((), (segment,)), True),
        )
    )
    node = ast_module.struct({"issues": ast_module.Arrays((), (issue,))})
    return Bottom(node)


StandardSchemaV1FailureResult: Final = _failure_result()
"""The schema of a Standard Schema failure result: ``issues``, each a
``message`` and an optional ``path`` of keys (numbers or strings) or
``{"key": ...}`` segments (Effect's ``Schema.StandardSchemaV1FailureResult``)."""


@dataclass(frozen=True, slots=True)
class JsonSchemaConverter:
    """``StandardJSONSchemaV1.Converter``: the JSON Schema of the encoded
    (``input``) or decoded (``output``) side, in a target dialect."""

    schema: Codec[object, object, object, object]

    def input(self, options: JsonSchemaOptions, /) -> JsonSchema:
        return _json_schema(self.schema.__codec__().ast, options["target"])

    def output(self, options: JsonSchemaOptions, /) -> JsonSchema:
        return _json_schema(self.schema.__codec__().ast.to_type(), options["target"])


@dataclass(frozen=True, slots=True)
class StandardProps[A]:
    """What ``~standard`` holds (``StandardSchemaV1.Props`` and
    ``StandardJSONSchemaV1.Props``); a member the adapter lacks is ``None``."""

    version: Literal[1] = 1
    vendor: str = "pyfect"
    validate: Validate[A] | None = None
    json_schema: JsonSchemaConverter | None = None


_KEY: Final = "~standard"


class StandardSchemaV1(Generic[T_co, E_co, RD_co, RE_co]):
    """A schema adapted to Standard Schema (see the module)."""

    __slots__ = ("__dict__", "__wrapped__")

    def __init__(
        self, schema: Codec[T_co, E_co, RD_co, RE_co], standard: StandardProps[T_co]
    ) -> None:
        object.__setattr__(self, "__wrapped__", schema)
        object.__setattr__(self, _KEY, standard)

    __wrapped__: Codec[T_co, E_co, RD_co, RE_co]

    @property
    def __standard__(self) -> StandardProps[T_co]:
        """The props at ``~standard``, typed."""
        return self.__dict__[_KEY]

    def __codec__(self) -> Bottom[T_co, E_co, RD_co, RE_co]:
        return self.__wrapped__.__codec__()

    def pipe[B](self, f: Callable[[StandardSchemaV1[T_co, E_co, RD_co, RE_co]], B], /) -> B:
        return f(self)

    def __getattr__(self, name: str) -> Any:
        schema = self.__wrapped__
        if isinstance(schema, type):
            # A class method reads its class through the adapter, so writes
            # to the adapter are what it sees.
            raw: object = inspect.getattr_static(schema, name, None)
            if isinstance(raw, classmethod):
                return MethodType(cast("classmethod[Any, Any, Any]", raw).__func__, self)
            if not inspect.isfunction(raw) and not isinstance(raw, staticmethod | type):
                get = getattr(type(raw), "__get__", None)
                if get is not None:
                    # A class-level accessor reads through the adapter too.
                    return get(raw, None, self)
        return getattr(schema, name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return cast("Callable[..., Any]", self.__wrapped__)(*args, **kwargs)

    def __instancecheck__(self, instance: object) -> bool:
        schema = self.__wrapped__
        return isinstance(schema, type) and isinstance(instance, schema)

    def __mro_entries__(self, bases: tuple[object, ...]) -> tuple[type, ...]:
        schema = self.__wrapped__
        if not isinstance(schema, type):
            raise TypeError("only an adapted schema class can be subclassed")
        return (schema,)

    def __repr__(self) -> str:
        return f"StandardSchemaV1({self.__wrapped__!r})"


def _target_and_props(schema: Codec[Any, Any, Any, Any]) -> tuple[Any, StandardProps[Any]]:
    if isinstance(schema, StandardSchemaV1):
        return schema.__wrapped__, schema.__standard__
    return schema, StandardProps()


def to_standard_schema_v1[T, E, RE](
    schema: Codec[T, E, Never, RE],
    /,
    *,
    leaf_hook: LeafHook | None = None,
    check_hook: CheckHook | None = None,
    parse_options: ParseOptions | None = None,
) -> StandardSchemaV1[T, E, Never, RE]:
    """``schema`` with a Standard Schema ``validate`` (see the module)."""
    target, props = _target_and_props(schema)
    decode = decode_unknown_effect(cast("Codec[T, object, Never, object]", target))
    options: ParseOptions = {"errors": "all", **(parse_options or {})}
    formatter = make_formatter_standard_schema_v1(leaf_hook=leaf_hook, check_hook=check_hook)

    def validate(
        value: object, _options: ValidateOptions | None = None, /
    ) -> Result[T] | Awaitable[Result[T]]:
        effect = decode(value, **options).match(
            on_failure=lambda error: cast("Result[T]", formatter(error.issue)),
            on_success=lambda decoded: cast("Result[T]", {"value": decoded}),
        )
        return _run(effect)

    return StandardSchemaV1(target, replace(props, validate=validate))


def _result[A](exit: Exit[Result[A], object]) -> Result[A]:
    if isinstance(exit, Success):
        return exit.value
    return {"issues": [{"message": exit.cause.pretty()}]}


def _run[A](effect: Any) -> Result[A] | Awaitable[Result[A]]:
    """The result now when the effect runs without waiting, else an
    awaitable of it (Effect's sync-first ``MixedScheduler``)."""
    scheduler = SyncScheduler()
    fiber: Fiber[Result[A], object] = new_root(scheduler, Context.empty())
    fiber._start(effect)  # pyright: ignore[reportPrivateUsage]
    scheduler.flush()
    done = fiber._exit  # pyright: ignore[reportPrivateUsage]
    if done is not None:
        return _result(done)

    async def later() -> Result[A]:
        return _result(await asyncio.to_thread(drive, scheduler, fiber))

    return later()


def _json_schema(ast: Any, target: Target) -> JsonSchema:
    document = to_json_schema_document(Bottom(ast))
    if target == "draft-2020-12":
        out: JsonSchema = {"$schema": META_SCHEMA_URI_DRAFT_2020_12, **document.schema}
        if document.definitions:
            out["$defs"] = dict(document.definitions)
        return out
    if target == "draft-07":
        draft07 = to_document_draft_07(document)
        out = {"$schema": META_SCHEMA_URI_DRAFT_07, **draft07.schema}
        if draft07.definitions:
            out["definitions"] = dict(draft07.definitions)
        return out
    raise ValueError(f"Unsupported target: {target}")


def to_standard_json_schema_v1[T, E, RD, RE](
    schema: Codec[T, E, RD, RE], /
) -> StandardSchemaV1[T, E, RD, RE]:
    """``schema`` with a Standard JSON Schema converter (see the module)."""
    target, props = _target_and_props(schema)
    return StandardSchemaV1(target, replace(props, json_schema=JsonSchemaConverter(target)))


__all__ = [
    "FailureResult",
    "Issue",
    "JsonSchemaConverter",
    "JsonSchemaOptions",
    "Result",
    "StandardProps",
    "StandardSchemaV1",
    "StandardSchemaV1FailureResult",
    "SuccessResult",
    "Target",
    "Validate",
    "ValidateOptions",
    "to_standard_json_schema_v1",
    "to_standard_schema_v1",
]
