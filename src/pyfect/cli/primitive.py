"""How one command-line string becomes a value (Effect's ``Primitive``).

A ``Primitive[A]`` has a ``tag`` (``"Boolean"``, ``"Int"``, ...) used for
help and completions, and ``parse``: the effect turning the text into an
``A`` or failing with a message for the user. Flags and arguments are
built on them; most programs never touch one directly::

    yield from primitive.integer.parse("42")  # 42
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, Literal, Never, TypeVar

from pyfect import _js_date as js_date
from pyfect import redacted as redacted_
from pyfect import schema as S
from pyfect._json_text import parse as parse_json
from pyfect._json_text import stringify
from pyfect.cli._environment import Environment
from pyfect.effect import Effect, fail, gen, succeed
from pyfect.encoding import ini, toml, yaml
from pyfect.file_system import FileSystem
from pyfect.path import Path
from pyfect.redacted import Redacted
from pyfect.schema import Codec
from pyfect.schema.issue import Issue

A_co = TypeVar("A_co", covariant=True)

type PathType = Literal["file", "directory", "either"]
type FileFormat = Literal["ini", "json", "toml", "yaml"]


@dataclass(frozen=True, slots=True, eq=False)
class Primitive(Generic[A_co]):
    """Parses one string into an ``A``; failures are messages for the user.
    ``choice_keys`` and ``path_type`` describe choices and paths to help
    and completions."""

    tag: str
    parse: Callable[[str], Effect[A_co, str, Environment]]
    choice_keys: tuple[str, ...] | None = None
    path_type: PathType | None = None


def _schema_primitive[A](tag: str, schema: Codec[A, object, Never, object]) -> Primitive[A]:
    decode = S.decode_unknown_effect(S.to_codec_string_tree(schema))
    return Primitive(tag, lambda value: decode(value).map_error(lambda error: error.message))


_TRUE_LITERALS = ("true", "yes", "on", "1", "y")
_FALSE_LITERALS = ("false", "no", "off", "0", "n")
_BOOLEAN_EXPECTED = "Expected " + " | ".join(
    stringify(v) for v in (*_TRUE_LITERALS, *_FALSE_LITERALS)
)


def is_true_literal(value: str) -> bool:
    return value in _TRUE_LITERALS


def is_false_literal(value: str) -> bool:
    return value in _FALSE_LITERALS


def _parse_boolean(value: str) -> Effect[bool, str]:
    if value in _TRUE_LITERALS:
        return succeed(True)
    if value in _FALSE_LITERALS:
        return succeed(False)
    return fail(_BOOLEAN_EXPECTED)


boolean: Primitive[bool] = Primitive("Boolean", _parse_boolean)
"""``true`` / ``yes`` / ``on`` / ``1`` / ``y`` and ``false`` / ``no`` /
``off`` / ``0`` / ``n``."""

finite: Primitive[float] = _schema_primitive("Finite", S.Finite)
"""A finite number, as JavaScript reads one (``1e3``, ``-42.5``)."""

integer: Primitive[int] = _schema_primitive("Int", S.Int)
"""An integer (``1e3`` is 1000; ``3.14`` is not one)."""


def _parse_date(value: str) -> Effect[datetime, str]:
    parsed = js_date.to_datetime(js_date.parse(value))
    return fail("Expected a valid Date") if parsed is None else succeed(parsed)


date_: Primitive[datetime] = Primitive("Date", _parse_date)
"""A date as JavaScript's ``Date`` reads it, as a UTC ``datetime``: ISO 8601
(a date alone is midnight UTC, a date-time without an offset local time)
or V8's other forms (``Jan 15 2024``, ``1/15/2024 10:00 PM``)."""

string: Primitive[str] = Primitive("String", succeed)


def choice[A](choices: Sequence[tuple[str, A]]) -> Primitive[A]:
    """One of the keys, giving its value; otherwise fails with the keys."""
    mapping = dict(choices)
    valid = " | ".join(stringify(key) for key, _ in choices)

    def parse(value: str) -> Effect[A, str]:
        if value in mapping:
            return succeed(mapping[value])
        return fail(valid)

    return Primitive("Choice", parse, choice_keys=tuple(key for key, _ in choices))


def _absolute(path: str):
    paths = yield from Path()
    return path if paths.is_absolute(path) else paths.resolve(path)


def path(path_type: PathType, must_exist: bool = False) -> Primitive[str]:
    """A path, resolved to an absolute one. With ``must_exist`` it must
    exist; an existing path must be of ``path_type``."""

    def parse(value: str) -> Effect[str, str, Environment]:
        def body():
            fs = yield from FileSystem()
            absolute = yield from _absolute(value)
            exists = yield from fs.exists(absolute).map_error(
                lambda e: f"Failed to check path existence: {e.message}"
            )
            if must_exist and not exists:
                return (yield from fail(f"Path does not exist: {absolute}"))
            if exists and path_type != "either":
                info = yield from fs.stat(absolute).map_error(
                    lambda e: f"Failed to stat path: {e.message}"
                )
                if path_type == "file" and info.type != "File":
                    return (yield from fail(f"Path is not a file: {absolute}"))
                if path_type == "directory" and info.type != "Directory":
                    return (yield from fail(f"Path is not a directory: {absolute}"))
            return absolute

        return gen(body)

    return Primitive("Path", parse, path_type=path_type)


redacted: Primitive[Redacted[str]] = Primitive(
    "Redacted", lambda value: succeed(redacted_.make(value))
)
"""The text, wrapped so it never shows in logs or output."""


def _read_file_text(file_path: str) -> Effect[str, str, Environment]:
    def body():
        fs = yield from FileSystem()
        absolute = yield from _absolute(file_path)
        exists = yield from fs.exists(absolute).map_error(
            lambda e: f"Failed to check file existence: {e.message}"
        )
        if not exists:
            return (yield from fail(f"File does not exist: {absolute}"))
        info = yield from fs.stat(absolute).map_error(lambda e: f"Failed to stat file: {e.message}")
        if info.type != "File":
            return (yield from fail(f"Path is not a file: {absolute}"))
        return (
            yield from fs.read_file_string(absolute).map_error(
                lambda e: f"Failed to read file: {e.message}"
            )
        )

    return gen(body)


file_text: Primitive[str] = Primitive("FileText", _read_file_text)
"""The contents of the file at the path."""


def _js_error_text(error: Exception) -> str:
    """JavaScript's ``${error}``: what the parsers raise as ``ValueError``,
    Effect's throw as ``SyntaxError``."""
    name = "SyntaxError" if type(error) is ValueError else type(error).__name__
    return f"{name}: {error}"


_FILE_PARSERS: dict[str, Callable[[str], object]] = {
    "ini": ini.parse,
    "json": parse_json,
    "toml": toml.parse,
    "yml": yaml.parse,
    "yaml": yaml.parse,
}


def file_parse(format: FileFormat | None = None) -> Primitive[object]:
    """The parsed contents of the file at the path: INI, JSON, TOML or YAML,
    by ``format`` or else the file's extension (``.yml`` is YAML too)."""

    def parse(file_path: str) -> Effect[object, str, Environment]:
        def body():
            file_format = format or file_path.rsplit(".", 1)[-1]
            parser = _FILE_PARSERS.get(file_format)
            if parser is None:
                return (yield from fail(f"Unsupported file format: {file_format}"))
            content = yield from _read_file_text(file_path)
            try:
                return parser(content)
            except Exception as error:
                return (
                    yield from fail(
                        f"Failed to parse '.{file_format}' file content: {_js_error_text(error)}"
                    )
                )

        return gen(body)

    return Primitive("FileParse", parse)


def file_schema[A](
    schema: Codec[A, object, Environment, object],
    *,
    format: FileFormat | None = None,
    error_formatter: Callable[[Issue], str] | None = None,
) -> Primitive[A]:
    """The file's parsed contents (as ``file_parse``) decoded by ``schema``;
    a decoding failure is ``error_formatter(issue)`` or the schema error's
    message."""
    decode = S.decode_unknown_effect(schema)
    parse_file = file_parse(format).parse

    def parse(file_path: str) -> Effect[A, str, Environment]:
        def body():
            content = yield from parse_file(file_path)
            return (
                yield from decode(content).map_error(
                    lambda error: error_formatter(error.issue) if error_formatter else error.message
                )
            )

        return gen(body)

    return Primitive("FileSchema", parse)


def _parse_key_value(value: str) -> Effect[dict[str, str], str]:
    key, separator, val = value.partition("=")
    if not separator:
        return fail(f"Invalid key=value format. Expected format: key=value, got: {value}")
    if not key or not val:
        return fail(f"Invalid key=value format. Both key and value must be non-empty. Got: {value}")
    return succeed({key: val})


key_value_pair: Primitive[dict[str, str]] = Primitive("KeyValuePair", _parse_key_value)
"""``key=value`` (the value may hold more ``=``), as a one-entry dict."""

never: Primitive[Never] = Primitive("Never", lambda _: fail("This option does not accept values"))
"""Accepts nothing."""

_TYPE_NAMES = {
    "Boolean": "boolean",
    "String": "string",
    "Int": "integer",
    "Finite": "number",
    "Date": "date",
    "Path": "path",
    "Choice": "choice",
    "Redacted": "string",
    "FileText": "file",
    "FileParse": "file",
    "FileSchema": "file",
    "KeyValuePair": "key=value",
    "Never": "none",
}


def type_name(primitive: Primitive[Any]) -> str:
    """The name help shows for the primitive's values."""
    return _TYPE_NAMES.get(primitive.tag, "value")


def is_boolean(primitive: Primitive[Any]) -> bool:
    return primitive.tag == "Boolean"


__all__ = [
    "FileFormat",
    "PathType",
    "Primitive",
    "boolean",
    "choice",
    "date_",
    "file_parse",
    "file_schema",
    "file_text",
    "finite",
    "integer",
    "is_boolean",
    "is_false_literal",
    "is_true_literal",
    "key_value_pair",
    "never",
    "path",
    "redacted",
    "string",
    "type_name",
]
