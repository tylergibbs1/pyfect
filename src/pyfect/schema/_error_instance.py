"""Exceptions in JSON (Effect's ``ErrorInstance`` and ``Defect``).

An error is written as Effect writes one: ``{"name", "message", "stack"?,
"cause"?}``, the name being the exception's class name, the stack its
formatted traceback (only with ``include_stack``), the cause its
``__cause__`` (unless ``exclude_cause``).

Reading one back never picks a class from the input (the input would
choose the code that runs): an error decodes to an ``ErrorInstance``, an
exception holding those fields as data; any other defect decodes to its JSON
value as it was.
"""

from __future__ import annotations

import traceback
from collections.abc import Mapping
from functools import cache
from typing import Never, TypeIs, cast

from pyfect import _json_text
from pyfect._json_value import JsonValue
from pyfect.logger._text import format_unknown
from pyfect.option import Option, Some
from pyfect.schema import ast
from pyfect.schema._codec_links import link
from pyfect.schema._declare import declare
from pyfect.schema._schema import Bottom
from pyfect.schema._transform import DecodeToSchema, decode_to
from pyfect.schema._values import Json
from pyfect.schema.transformation import transform


class ErrorInstance(Exception):
    """An error read from its JSON form, as Effect's ``Error`` with the
    ``name`` the input gave (the class stays this one, whatever the name):
    its ``message``, ``name``, ``stack`` and ``cause`` (``Some`` of the decoded
    cause, ``Some(None)`` for a ``null`` one). Equal when those are.

    The class is also the schema of errors (Effect's ``ErrorInstance()``):
    it takes an exception (``Expected Error`` otherwise), written in JSON
    as above. ``ErrorInstance.schema`` takes the options."""

    message: str
    name: str
    stack: str | None
    cause: Option[object]

    def __init__(
        self,
        message: str,
        *,
        name: str = "Error",
        stack: str | None = None,
        cause: Option[object] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.name = name
        self.stack = stack
        self.cause = cause

    def __eq__(self, other: object) -> bool:
        return (
            type(other) is ErrorInstance
            and other.message == self.message
            and other.name == self.name
            and other.stack == self.stack
            and other.cause == self.cause
        )

    def __hash__(self) -> int:
        return hash((self.name, self.message))

    def __repr__(self) -> str:
        return (
            f"ErrorInstance({self.message!r}, name={self.name!r}, "
            f"stack={self.stack!r}, cause={self.cause!r})"
        )

    @classmethod
    def __codec__(cls) -> Bottom[BaseException]:
        return cls.schema()

    @staticmethod
    def schema(
        *, include_stack: bool = False, exclude_cause: bool = False
    ) -> Bottom[BaseException]:
        """The schema of errors; ``include_stack`` writes the stack,
        ``exclude_cause`` leaves the cause out. The same options give the
        same schema."""
        return error_schema(include_stack, exclude_cause)


def _unknown_as_json(value: object) -> JsonValue:
    # JSON's reading of it, or its text when JSON has none (Effect's
    # ``encodeUnknownAsJson``).
    try:
        return _json_text.parse(_json_text.stringify(cast("JsonValue", value)))
    except (*_json_text.STRINGIFY_ERRORS, ValueError):
        return format_unknown(value)


def _is_json_error(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping) and isinstance(
        cast("Mapping[str, object]", value).get("message"), str
    )


def _decode_error(encoded: Mapping[str, object]) -> ErrorInstance:
    name = encoded.get("name")
    stack = encoded.get("stack")
    return ErrorInstance(
        cast("str", encoded["message"]),
        name=name if isinstance(name, str) else "Error",
        stack=stack if isinstance(stack, str) else None,
        cause=Some(_decode_value(cast("JsonValue", encoded["cause"])))
        if "cause" in encoded
        else None,
    )


def _decode_value(value: JsonValue) -> object:
    return _decode_error(value) if _is_json_error(value) else value


def _encode(value: object, *, include_stack: bool, exclude_cause: bool) -> JsonValue:
    """``value`` (an exception, an ``ErrorInstance`` or a JSON value) in
    JSON; an error that is its own cause is ``"[Circular]"`` there."""
    seen: set[int] = set()

    def go(value: object) -> JsonValue:
        if not isinstance(value, BaseException):
            return _unknown_as_json(value)
        if id(value) in seen:
            return "[Circular]"
        seen.add(id(value))
        try:
            return error(value)
        finally:
            seen.discard(id(value))

    def error(value: BaseException) -> dict[str, JsonValue]:
        if isinstance(value, ErrorInstance):
            encoded: dict[str, JsonValue] = {"name": value.name, "message": value.message}
            stack, cause = value.stack, value.cause
        else:
            encoded = {"name": type(value).__name__, "message": str(value)}
            frames = value.__traceback__
            stack = None if frames is None else "".join(traceback.format_exception(value))
            cause = None if value.__cause__ is None else Some(value.__cause__)
        if include_stack and stack is not None:
            encoded["stack"] = stack
        if not exclude_cause and cause is not None:
            encoded["cause"] = go(cause.value)
        return encoded

    return go(value)


_JSON_ERROR = ast.Objects(
    (
        ast.PropertySignature("message", ast.string),
        ast.PropertySignature("name", ast.string, optional=True),
        ast.PropertySignature("stack", ast.string, optional=True),
        ast.PropertySignature("cause", ast.json, optional=True),
    )
)


def _is_error(value: object) -> TypeIs[BaseException]:
    return isinstance(value, BaseException)


@cache
def error_schema(include_stack: bool, exclude_cause: bool) -> Bottom[BaseException]:
    def encode(value: BaseException) -> Mapping[str, object]:
        encoded = _encode(value, include_stack=include_stack, exclude_cause=exclude_cause)
        return cast("Mapping[str, object]", encoded)

    def to_json(_: tuple[ast.AST, ...]) -> ast.Link:
        return link(_JSON_ERROR, decode=_decode_error, encode=encode)

    options = {
        **({"includeStack": True} if include_stack else {}),
        **({"excludeCause": True} if exclude_cause else {}),
    }
    return declare(
        _is_error,
        expected="Error",
        representation={"id": "effect/schema/Error", "payload": options or None},
        to_codec_json=to_json,
    )


type DefectSchema = DecodeToSchema[object, JsonValue, Never, Never]


def Defect(*, include_stack: bool = False, exclude_cause: bool = False) -> DefectSchema:
    """A defect in JSON (Effect's ``Defect()``), for a ``Cause`` or ``Exit``
    crossing a JSON boundary: an exception is written as an error (see
    ``ErrorInstance``), anything else as JSON or its text; a JSON object with
    a string ``message`` decodes to an ``ErrorInstance``, any other JSON
    value to itself. The same options give the same schema."""
    return _defect_schema(include_stack, exclude_cause)


def _is_anything(_: object) -> TypeIs[object]:
    return True


@cache
def _defect_schema(include_stack: bool, exclude_cause: bool) -> DefectSchema:
    def encode(value: object) -> JsonValue:
        return _encode(value, include_stack=include_stack, exclude_cause=exclude_cause)

    def to_json(_: tuple[ast.AST, ...]) -> ast.Link:
        return link(ast.json, decode=_decode_value, encode=encode)

    # The decoded side is written the same way, so it is drawn from JSON too.
    anything = declare(_is_anything, expected="Defect", to_codec_json=to_json)
    return Json.pipe(decode_to(anything, transform(decode=_decode_value, encode=encode)))
