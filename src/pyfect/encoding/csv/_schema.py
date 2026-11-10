"""CSV channels that decode records with a schema, or encode values with
one: ``decode_schema_string``, ``decode_schema``, ``encode_schema_string``
and ``encode_schema``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Never, Unpack, cast

from pyfect._json_text import quote
from pyfect._primitives import _Sync
from pyfect.channel import Channel, decode_text, from_transform
from pyfect.channel._base import AnyPull
from pyfect.encoding.csv._channels import (
    DEFAULT_MAX_RECORD_SIZE,
    Decoded,
    Newline,
    decode_records,
    encode_records,
)
from pyfect.encoding.csv._error import CsvError
from pyfect.schema import Codec, NonEmptyArray, ParseOptions, SchemaError, ast, to_codec_string_tree
from pyfect.schema import decode_unknown_effect as decode_with
from pyfect.schema import encode_effect as encode_with
from pyfect.schema._undefined import is_undefined
from pyfect.schema.issue import Composite, Issue, Pointer
from pyfect.scope import CloseableScope

type _AnyChannel = Channel[Any, Any, Any, Any, Any, Any, Any]


def _rebase(error: SchemaError, record: Callable[[int], int]) -> SchemaError:
    """``error`` with the chunk index heading each top-level path replaced by
    the record number."""
    issue = error.issue
    if not isinstance(issue, Composite):
        return error

    def rebased(inner: Issue) -> Issue:
        if isinstance(inner, Pointer) and inner.path and type(inner.path[0]) is int:
            return Pointer((record(inner.path[0]), *inner.path[1:]), inner.issue)
        return inner

    first, *rest = issue.issues
    return SchemaError(Composite(issue.ast, (rebased(first), *map(rebased, rest)), issue.input))


def _to_codec[T, RD, RE](
    schema: Codec[T, Any, RD, RE], disable_codecs: bool
) -> Codec[T, Any, RD, RE]:
    """The schema of the cells: by default wrapped in ``to_codec_string_tree``,
    which keeps the decoded side and only changes the encoded one."""
    if disable_codecs:
        return schema
    return cast("Codec[T, Any, RD, RE]", to_codec_string_tree(schema))


def _is_string_leaf(node: ast.AST) -> bool:
    match node:
        case ast.String() | ast.TemplateLiteral():
            return True
        case ast.Literal():
            return isinstance(node.literal, str)
        case ast.Enum():
            return all(isinstance(member.value, str) for member in node.enum)
        case ast.Union():
            return all(is_undefined(member) or _is_string_leaf(member) for member in node.types)
        case _:
            return False


def _resolve_suspend(node: ast.AST) -> ast.AST:
    while isinstance(node, ast.Suspend):
        node = node.target
    return node


def _check_cells(node: ast.AST, columns: Sequence[str] | None) -> None:
    """Raises unless every selected cell of an encoded struct or tuple is a string."""
    node = _resolve_suspend(node)

    def check(name: str, type: ast.AST) -> None:
        if not _is_string_leaf(type):
            raise ValueError(
                f"Csv: {name} encodes to {type.tag}, not a string. "
                "Encode it as a single cell with a transformation, such as "
                "SchemaGetter.split for arrays"
            )

    match node:
        case ast.Objects():
            for property in node.properties:
                name = property.name
                if isinstance(name, str) and (columns is None or name in columns):
                    check(f"column {quote(name)}", property.type)
            for index in node.index_signatures:
                check("index signature", index.type)
        case ast.Arrays():
            for i, element in enumerate(node.elements):
                check(f"column {i + 1}", element.type)
            for type in node.rest:
                check("rest element", type)
        case ast.Union():
            for member in node.types:
                _check_cells(member, columns)
        case _:
            raise ValueError(
                f"Csv: cannot verify string cells for {node.tag}. "
                "Encode it as a flat struct or tuple with a transformation"
            )


def decode_schema_string[T, RD, E = Never, D = None](
    schema: Codec[T, Any, RD, object],
    /,
    *,
    headers: bool = False,
    delimiter: str = ",",
    max_record_size: float = DEFAULT_MAX_RECORD_SIZE,
    ignore_empty_lines: bool = False,
    disable_codecs: bool = False,
    **options: Unpack[ParseOptions],
) -> Channel[tuple[T, ...], E | CsvError | SchemaError, D, tuple[str, ...], E, D, RD]:
    """Parse chunks of text as ``decode_string`` does and decode each record
    with ``schema``: a dict keyed by header name with ``headers``, else a row.
    By default the schema is wrapped in ``to_codec_string_tree``, so columns
    may be numbers, booleans or dates, and with ``headers`` an empty cell of a
    key that is optional on the encoded side is a missing key;
    ``disable_codecs`` decodes with ``schema`` as given. A column that does
    not encode to a string (a list, a nested struct) raises ``ValueError``
    here. Each chunk is decoded at once; a failure is a ``SchemaError`` whose
    paths start with the record number."""
    codec = _to_codec(schema, disable_codecs)
    encoded = _resolve_suspend(ast.to_encoded(codec.__codec__().ast))
    _check_cells(encoded, None)
    # CSV cannot tell an empty cell from a missing one, so empty cells of
    # optional keys are decoded as missing keys.
    optional = (
        [
            property.name
            for property in encoded.properties
            if isinstance(property.name, str)
            and (property.optional or ast.is_optional(property.type))
        ]
        if not disable_codecs and headers and isinstance(encoded, ast.Objects)
        else []
    )

    def value_of(record: Decoded) -> object:
        value = record.value
        if not optional or not isinstance(value, dict):
            return value
        # Header records are made per row, so they can be changed in place.
        for key in optional:
            if value.get(key) == "":
                del value[key]
        return value

    decode = decode_with(NonEmptyArray(codec), **options)

    def decoded(records: tuple[Decoded, ...]) -> Any:
        return decode(tuple(map(value_of, records))).map_error(
            lambda error: _rebase(error, lambda index: records[index].record)
        )

    channel: _AnyChannel = decode_records(delimiter, max_record_size, ignore_empty_lines, headers)
    return channel.map_effect(decoded)


def decode_schema[T, RD, E = Never, D = None](
    schema: Codec[T, Any, RD, object],
    /,
    *,
    headers: bool = False,
    delimiter: str = ",",
    max_record_size: float = DEFAULT_MAX_RECORD_SIZE,
    ignore_empty_lines: bool = False,
    disable_codecs: bool = False,
    **options: Unpack[ParseOptions],
) -> Channel[tuple[T, ...], E | CsvError | SchemaError, D, tuple[bytes, ...], E, D, RD]:
    """``decode_schema_string`` of UTF-8 bytes."""
    text: _AnyChannel = decode_text("utf-8", ignore_bom=True)
    records: _AnyChannel = decode_schema_string(
        schema,
        headers=headers,
        delimiter=delimiter,
        max_record_size=max_record_size,
        ignore_empty_lines=ignore_empty_lines,
        disable_codecs=disable_codecs,
        **options,
    )
    return text.pipe_to(records)


def _schema_columns(
    node: ast.AST, columns: Sequence[str] | None, headers: bool
) -> Sequence[str] | None:
    """The columns to write: ``columns``, else a struct's encoded keys in
    order; tuples and arrays write by position. Other schemas, records among
    them, need explicit columns."""
    if columns is not None:
        _check_cells(node, columns)
        return columns
    if isinstance(node, ast.Objects) and not node.index_signatures:
        names = [p.name for p in node.properties if isinstance(p.name, str)]
        _check_cells(node, names)
        return names
    if isinstance(node, ast.Arrays):
        if headers:
            raise ValueError("Csv: headers for tuple or array schemas require columns")
        _check_cells(node, None)
        return None
    raise ValueError(f"Csv: columns are required to encode {node.tag} schemas")


def _encode_schema_records[T, RE](
    schema: Codec[T, Any, object, RE],
    *,
    delimiter: str,
    newline: Newline,
    columns: Sequence[str] | None,
    headers: bool,
    disable_codecs: bool,
) -> _AnyChannel:
    codec = _to_codec(schema, disable_codecs)
    names = _schema_columns(ast.to_encoded(codec.__codec__().ast), columns, headers)
    writer: _AnyChannel = encode_records(delimiter, newline, names, headers)
    encode = encode_with(NonEmptyArray(codec))
    first_record = 2 if headers else 1

    def build(upstream: AnyPull) -> AnyPull:
        record = [first_record]

        def encoded(chunk: tuple[T, ...]) -> AnyPull:
            first = record[0]
            record[0] += len(chunk)
            items = cast("tuple[T, *tuple[T, ...]]", chunk)
            return encode(items).map_error(
                lambda error: _rebase(error, lambda index: first + index)
            )

        return upstream.flat_map(encoded)

    def transform(upstream: AnyPull, _scope: CloseableScope) -> AnyPull:
        return _Sync(lambda: build(upstream))

    values: _AnyChannel = from_transform(transform)
    return values.pipe_to(writer)


def encode_schema_string[T, RE, E = Never, D = None](
    schema: Codec[T, Any, object, RE],
    /,
    *,
    columns: Sequence[str] | None = None,
    headers: bool = False,
    delimiter: str = ",",
    newline: Newline = "\r\n",
    disable_codecs: bool = False,
) -> Channel[tuple[str, ...], E | SchemaError, D, tuple[T, ...], E, D, RE]:
    """Encode each value with ``schema`` and write it as CSV text, one string
    per record. By default the schema is wrapped in ``to_codec_string_tree``,
    so every column encodes to a string (``disable_codecs`` keeps it as
    given). ``columns`` defaults to a struct's encoded keys (renamed ones
    too) and is needed for other mappings; tuples and arrays write cells by
    position and use ``columns`` only as header names. A missing or ``None``
    value is an empty cell. A column that does not encode to a string raises
    ``ValueError`` here. A failure is a ``SchemaError`` whose paths start
    with the output record number, the header row counted."""
    return _encode_schema_records(
        schema,
        delimiter=delimiter,
        newline=newline,
        columns=columns,
        headers=headers,
        disable_codecs=disable_codecs,
    )


def encode_schema[T, RE, E = Never, D = None](
    schema: Codec[T, Any, object, RE],
    /,
    *,
    columns: Sequence[str] | None = None,
    headers: bool = False,
    delimiter: str = ",",
    newline: Newline = "\r\n",
    disable_codecs: bool = False,
) -> Channel[tuple[bytes, ...], E | SchemaError, D, tuple[T, ...], E, D, RE]:
    """``encode_schema_string`` as UTF-8 bytes, one ``bytes`` per input
    chunk. When the bytes stream an HTTP response body, an encoding failure
    ends the body; it cannot change a status already sent."""
    from pyfect.encoding.csv._channels import _joined_bytes

    records = _encode_schema_records(
        schema,
        delimiter=delimiter,
        newline=newline,
        columns=columns,
        headers=headers,
        disable_codecs=disable_codecs,
    )
    return records.map(_joined_bytes)


__all__ = ["decode_schema", "decode_schema_string", "encode_schema", "encode_schema_string"]
