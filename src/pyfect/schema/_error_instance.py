"""Exceptions in JSON (Effect's ``ErrorInstance`` and ``Defect``).

An error is written as Effect writes one: ``{"name", "message", "stack"?,
"cause"?}``, the name being the exception's class name, the stack its
formatted traceback (only with ``include_stack``), the cause its
``__cause__`` (unless ``exclude_cause``).

Reading one back never picks a class from the input (the input would
choose the code that runs): an error decodes to an ``ErrorInstance``, a
frozen dataclass holding those fields as data. A ``Die`` holds an
exception, so a decoded defect is a ``DecodedDefect`` holding the decoded
value (an ``ErrorInstance``, or any other JSON value as it was).
"""

from __future__ import annotations

import traceback
from collections.abc import Mapping, Sequence
from dataclasses import KW_ONLY, dataclass
from functools import cache
from typing import Never, TypeIs, cast

from pyfect import _json_text
from pyfect._json_value import JsonValue
from pyfect.logger._text import format_unknown
from pyfect.option import Option, Some
from pyfect.schema import ast
from pyfect.schema._codec_links import link
from pyfect.schema._declare import declare, instance_of
from pyfect.schema._schema import Bottom
from pyfect.schema._transform import DecodeToSchema, decode_to
from pyfect.schema._values import Json
from pyfect.schema.transformation import transform


@dataclass(frozen=True, slots=True)
class ErrorInstance:
    """An error read from its JSON form: its ``name`` (the class name it
    was written with), ``message``, ``stack`` and ``cause`` (``Some`` of
    the decoded cause, ``Some(None)`` for a ``null`` one).

    The class is also the schema of errors (Effect's ``ErrorInstance()``):
    it takes an exception or an ``ErrorInstance`` (``Expected Error``
    otherwise), both written in JSON as above. ``ErrorInstance.schema``
    takes the options."""

    message: str
    _: KW_ONLY
    name: str = "Error"
    stack: str | None = None
    cause: Option[ErrorInstance | JsonValue] = None

    @classmethod
    def __codec__(cls) -> Bottom[BaseException | ErrorInstance]:
        return cls.schema()

    @staticmethod
    def schema(
        *, include_stack: bool = False, exclude_cause: bool = False
    ) -> Bottom[BaseException | ErrorInstance]:
        """The schema of errors; ``include_stack`` writes the stack,
        ``exclude_cause`` leaves the cause out. The same options give the
        same schema."""
        return _error_schema(include_stack, exclude_cause)


def _text_of(value: JsonValue) -> str:
    # JSON text, or (for a non-finite number) as Effect's formatter writes it.
    try:
        return _json_text.stringify(value)
    except _json_text.STRINGIFY_ERRORS:
        return format_unknown(value)


class DecodedDefect(Exception):
    """A defect read from its JSON form: ``value`` is the decoded
    ``ErrorInstance``, or the JSON value when it was not an error. Its text
    is the error's message. Equal when the values are."""

    value: ErrorInstance | JsonValue

    def __init__(self, value: ErrorInstance | JsonValue) -> None:
        text = value.message if isinstance(value, ErrorInstance) else _text_of(value)
        super().__init__(text)
        self.value = value

    def __eq__(self, other: object) -> bool:
        return type(other) is DecodedDefect and other.value == self.value

    def __hash__(self) -> int:
        # Only what equal values share: key order and number types differ.
        value = self.value
        if isinstance(value, ErrorInstance):
            return hash((value.name, value.message))
        if isinstance(value, Mapping):
            return hash(frozenset(value))
        if isinstance(value, Sequence) and not isinstance(value, str):
            return hash(len(value))
        return hash(value)

    def __repr__(self) -> str:
        return f"DecodedDefect({self.value!r})"


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


def _decode_value(value: JsonValue) -> ErrorInstance | JsonValue:
    return _decode_error(value) if _is_json_error(value) else value


def _encode(value: object, *, include_stack: bool, exclude_cause: bool) -> JsonValue:
    """``value`` (an exception, an ``ErrorInstance`` or a JSON value) in
    JSON; an error that is its own cause is ``"[Circular]"`` there."""
    seen: set[int] = set()

    def go(value: object) -> JsonValue:
        if isinstance(value, DecodedDefect):
            return go(value.value)
        if not isinstance(value, BaseException | ErrorInstance):
            return cast("JsonValue", value)
        if id(value) in seen:
            return "[Circular]"
        seen.add(id(value))
        try:
            return error(value)
        finally:
            seen.discard(id(value))

    def error(value: BaseException | ErrorInstance) -> dict[str, JsonValue]:
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


def _is_error(value: object) -> TypeIs[BaseException | ErrorInstance]:
    return isinstance(value, BaseException | ErrorInstance)


@cache
def _error_schema(
    include_stack: bool, exclude_cause: bool
) -> Bottom[BaseException | ErrorInstance]:
    def encode(value: BaseException | ErrorInstance) -> Mapping[str, object]:
        encoded = _encode(value, include_stack=include_stack, exclude_cause=exclude_cause)
        return cast("Mapping[str, object]", encoded)

    def to_json(_: tuple[ast.AST, ...]) -> ast.Link:
        return link(_JSON_ERROR, decode=_decode_error, encode=encode)

    return declare(_is_error, expected="Error", to_codec_json=to_json)


type DefectSchema = DecodeToSchema[BaseException, JsonValue, Never, Never]


def Defect(*, include_stack: bool = False, exclude_cause: bool = False) -> DefectSchema:
    """A defect in JSON (Effect's ``Defect()``), for a ``Cause`` or ``Exit``
    crossing a JSON boundary: an exception is written as an error (see
    ``ErrorInstance``); a JSON object with a string ``message`` decodes to
    a ``DecodedDefect`` of an ``ErrorInstance``, any other JSON value to a
    ``DecodedDefect`` of it. The same options give the same schema."""
    return _defect_schema(include_stack, exclude_cause)


@cache
def _defect_schema(include_stack: bool, exclude_cause: bool) -> DefectSchema:
    def decode(value: JsonValue) -> BaseException:
        return DecodedDefect(_decode_value(value))

    def encode(value: BaseException) -> JsonValue:
        return _encode(value, include_stack=include_stack, exclude_cause=exclude_cause)

    def to_json(_: tuple[ast.AST, ...]) -> ast.Link:
        return link(ast.json, decode=decode, encode=encode)

    # The decoded side is written the same way, so it is drawn from JSON too.
    exceptions = instance_of(BaseException, to_codec_json=to_json)
    return Json.pipe(decode_to(exceptions, transform(decode=decode, encode=encode)))
