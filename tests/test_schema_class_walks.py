"""Every schema walk that reaches into fields reaches into each kind of schema class too.

Effect's classes are declarations linked to their struct, so its walks meet the fields through
the link; pyfect's are ``ast.Class`` nodes, and a walk that matches only on ``Objects`` skips
them. Each walk here runs against every class kind, alone and in a union.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.ai.anthropic_structured_output import to_codec_anthropic
from pyfect.ai.openai_structured_output import to_codec_openai
from pyfect.encoding import csv
from pyfect.http import multipart
from pyfect.http_api import endpoint as ep
from pyfect.http_api import openapi
from pyfect.http_api import schema as api_schema
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup


class Plain(S.Class):
    tags: tuple[str, ...] = S.field(S.Array(S.String))


class PlainError(S.Error):
    tags: tuple[str, ...] = S.field(S.Array(S.String))


class Tagged(S.TaggedClass):
    tags: tuple[str, ...] = S.field(S.Array(S.String))


class TaggedErr(S.TaggedError):
    tags: tuple[str, ...] = S.field(S.Array(S.String))


CLASS_KINDS: list[Any] = [Plain, PlainError, Tagged, TaggedErr]


def _encoded(cls: Any, tags: object) -> dict[str, object]:
    tag = getattr(cls, "_tag", None)
    return {"tags": tags} if tag is None else {"_tag": tag, "tags": tags}


@pytest.mark.parametrize("cls", CLASS_KINDS, ids=lambda cls: cls.__name__)
def test_to_codec_array_from_single_decodes_a_single_value_in_every_class_kind(cls: Any) -> None:
    decode = S.decode_unknown_sync(S.to_codec_array_from_single(cls))
    assert decode(_encoded(cls, "a")) == cls(tags=("a",))
    assert decode(_encoded(cls, ["a", "b"])) == cls(tags=("a", "b"))


@pytest.mark.parametrize("cls", CLASS_KINDS, ids=lambda cls: cls.__name__)
def test_to_codec_array_from_single_reaches_classes_in_unions_and_string_trees(cls: Any) -> None:
    schema = S.to_codec_array_from_single(S.to_codec_string_tree(S.Union(cls, S.Int)))
    assert S.decode_unknown_sync(schema)(_encoded(cls, "a")) == cls(tags=("a",))
    assert S.decode_unknown_sync(schema)("1") == 1


@pytest.mark.parametrize("cls", CLASS_KINDS, ids=lambda cls: cls.__name__)
def test_to_codec_array_from_single_keeps_encoding_and_is_idempotent(cls: Any) -> None:
    schema = S.to_codec_array_from_single(cls)
    assert S.encode_sync(schema)(cls(tags=("a",))) == _encoded(cls, ("a",))
    assert S.to_codec_array_from_single(schema).ast is schema.ast


class Row(S.Class):
    id: str
    n: float = S.field(S.Finite)


class RowError(S.Error):
    id: str
    n: float = S.field(S.Finite)


class TaggedRow(S.TaggedClass):
    id: str
    n: float = S.field(S.Finite)


class TaggedRowError(S.TaggedError):
    id: str
    n: float = S.field(S.Finite)


ROW_KINDS: list[Any] = [Row, RowError, TaggedRow, TaggedRowError]


def _row_text(cls: Any, n: str) -> str:
    tag = getattr(cls, "_tag", None)
    return f"id,n\r\na,{n}\r\n" if tag is None else f"_tag,id,n\r\n{tag},a,{n}\r\n"


def _csv_decoded(schema: Any, text: str) -> object:
    channel = csv.decode_schema_string(schema, headers=True)
    return fx.run_blocking(
        stream.from_iterable([text]).pipe_through_channel(channel).run_collect().or_die()
    )


@pytest.mark.parametrize("cls", ROW_KINDS, ids=lambda cls: cls.__name__)
def test_csv_decodes_and_encodes_every_class_kind(cls: Any) -> None:
    assert _csv_decoded(cls, _row_text(cls, "1.5")) == [cls(id="a", n=1.5)]
    channel = csv.encode_schema_string(cls, headers=True)
    written = fx.run_blocking(
        stream.make(cls(id="a", n=1.5)).pipe_through_channel(channel).run_string().or_die()
    )
    assert written == _row_text(cls, "1.5")


@pytest.mark.parametrize("cls", ROW_KINDS, ids=lambda cls: cls.__name__)
def test_csv_decodes_a_union_of_classes(cls: Any) -> None:
    class Other(S.TaggedClass):
        id: str

    schema = S.Union(cls, Other)
    text = _row_text(cls, "2")
    assert _csv_decoded(schema, text) == [cls(id="a", n=2)]


@pytest.mark.parametrize("cls", ROW_KINDS, ids=lambda cls: cls.__name__)
def test_csv_still_refuses_a_class_whose_field_is_not_one_cell(cls: Any) -> None:
    class Nested(S.Class):
        row: Any = S.field(cls)

    with pytest.raises(ValueError, match='column "row" encodes to'):
        csv.decode_schema_string(Nested, headers=True)


class Pair(S.Class):
    pair: tuple[str, float] = S.field(S.Tuple(S.String, S.Finite))


class PairError(S.Error):
    pair: tuple[str, float] = S.field(S.Tuple(S.String, S.Finite))


class TaggedPair(S.TaggedClass):
    pair: tuple[str, float] = S.field(S.Tuple(S.String, S.Finite))


class TaggedPairError(S.TaggedError):
    pair: tuple[str, float] = S.field(S.Tuple(S.String, S.Finite))


@pytest.mark.parametrize("to_codec", [to_codec_openai, to_codec_anthropic])
@pytest.mark.parametrize(
    "cls", [Pair, PairError, TaggedPair, TaggedPairError], ids=lambda cls: cls.__name__
)
def test_structured_output_rewrites_the_fields_of_every_class_kind(cls: Any, to_codec: Any) -> None:
    codec = to_codec(cls).codec
    tag = getattr(cls, "_tag", None)
    output: dict[str, object] = {"pair": {"0": "a", "1": 1}}
    if tag is not None:
        output["_tag"] = tag
    assert S.decode_unknown_sync(codec)(output) == cls(pair=("a", 1))
    assert S.encode_sync(codec)(cls(pair=("a", 1))) == output


class OptionalRow(S.Class):
    id: str
    n: int | None = S.field(S.Union(S.Int, S.Undefined), default=None)


class OptionalRowError(S.Error):
    id: str
    n: int | None = S.field(S.Union(S.Int, S.Undefined), default=None)


class TaggedOptionalRow(S.TaggedClass):
    id: str
    n: int | None = S.field(S.Union(S.Int, S.Undefined), default=None)


class TaggedOptionalRowError(S.TaggedError):
    id: str
    n: int | None = S.field(S.Union(S.Int, S.Undefined), default=None)


OPTIONAL_ROW_KINDS: list[Any] = [
    OptionalRow,
    OptionalRowError,
    TaggedOptionalRow,
    TaggedOptionalRowError,
]


def _optional_row_text(cls: Any, *ns: str) -> str:
    tag = getattr(cls, "_tag", None)
    if tag is None:
        return "id,n\r\n" + "".join(f"a,{n}\r\n" for n in ns)
    return "_tag,id,n\r\n" + "".join(f"{tag},a,{n}\r\n" for n in ns)


@pytest.mark.parametrize("cls", OPTIONAL_ROW_KINDS, ids=lambda cls: cls.__name__)
def test_csv_reads_an_empty_cell_of_a_class_optional_field_as_missing(cls: Any) -> None:
    text = _optional_row_text(cls, "", "2")
    assert _csv_decoded(cls, text) == [cls(id="a"), cls(id="a", n=2)]
    assert _csv_decoded(S.suspend(lambda: cls), text) == [cls(id="a"), cls(id="a", n=2)]


@pytest.mark.parametrize("cls", OPTIONAL_ROW_KINDS, ids=lambda cls: cls.__name__)
def test_csv_reads_empty_optional_cells_by_the_union_member_of_classes_it_selects(
    cls: Any,
) -> None:
    class Other(S.TaggedClass):
        id: str
        n: str

    schema = S.Union(Other, cls)
    assert _csv_decoded(schema, _optional_row_text(cls, "")) == [cls(id="a")]
    assert _csv_decoded(schema, "_tag,id,n\r\nOther,a,\r\n") == [Other(id="a", n="")]


# Each walk that reads the keys of an encoded mapping, run over a struct and a class of the
# same fields: it must see the same keys in both.


class _IdRow(TypedDict):
    id: str
    n: NotRequired[int]


class IdRow(S.Class, identifier="Row"):
    id: str
    n: int | None = S.field(S.Union(S.Int, S.Undefined), default=None)


class _FileForm(TypedDict):
    file: Any


class FileForm(S.Class, identifier="Form"):
    file: Any = S.field(multipart.SingleFileSchema)


_RESERVED = api_schema.RESERVED_STREAM_FAILURE_EVENT


class _ReservedEvent(TypedDict):
    event: str
    data: str


class ReservedEvent(S.Class, identifier="Event"):
    event: str = S.field(S.Literal(_RESERVED))
    data: str


def _cell(row: object, key: str) -> object:
    return row.get(key) if isinstance(row, dict) else getattr(row, key)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


def _cells(schema: Any) -> object:
    rows: Any = _csv_decoded(schema, "id,n\r\na,\r\nb,2\r\n")
    return [(_cell(r, "id"), _cell(r, "n")) for r in rows]


def _spec(endpoint: Any) -> dict[str, Any]:
    return openapi.from_api(HttpApi.make("api").add(HttpApiGroup.make("g").add(endpoint)))


def _path_params(schema: Any) -> object:
    return list(_spec(ep.get("a", "/a/:id/:x", params=schema))["paths"])


def _multipart_form(schema: Any) -> object:
    spec = _spec(ep.post("a", "/a", payload=api_schema.as_multipart(schema)))
    found = spec["paths"]["/a"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
    ref = found.get("$ref")
    return found if ref is None else spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]


def _sse_events(schema: Any) -> object:
    try:
        ep.get("a", "/a", success=api_schema.StreamSse(events=schema))
    except ValueError as error:
        return str(error)
    return None


def _encoded_keys(schema: Any) -> object:
    return S.encode_sync(schema.pipe(S.encode_keys({"id": "key"})))(
        S.decode_unknown_sync(schema)({"id": "a"})
    )


_WALKS: list[tuple[str, Callable[[Any], object], Any, Any]] = [
    ("csv empty optional cells", _cells, S.Struct(_IdRow), IdRow),
    ("http_api path params", _path_params, S.Struct(_IdRow), IdRow),
    (
        "openapi multipart files",
        _multipart_form,
        S.Struct(_FileForm, file=multipart.SingleFileSchema),
        FileForm,
    ),
    (
        "StreamSse reserved event",
        _sse_events,
        S.Struct(_ReservedEvent, event=S.Literal(_RESERVED)),
        ReservedEvent,
    ),
    ("encode_keys", _encoded_keys, S.Struct(_IdRow), IdRow),
]


@pytest.mark.parametrize(
    ("walk", "struct", "cls"), [w[1:] for w in _WALKS], ids=[w[0] for w in _WALKS]
)
def test_a_walk_sees_a_class_as_the_struct_of_its_fields(
    walk: Callable[[Any], object], struct: Any, cls: Any
) -> None:
    assert walk(cls) == walk(struct)
