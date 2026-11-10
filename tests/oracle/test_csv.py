"""Ports of Effect's ``encoding/Csv.test.ts``. Each test's docstring is the
Effect test title. A row is a tuple of cells and a header record a dict;
``Stream.fromArray`` is ``stream.from_iterable`` (one chunk), and
``Schema.Date`` is ``S.DateTimeUtc``, Python's date-time schema."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import stream, testing
from pyfect.encoding import csv
from pyfect.schema import transformation as T
from pyfect.schema.issue import make_formatter_standard_schema_v1


def _run(inputs: list[Any], channel: Any) -> fx.Effect[list[Any], Any]:
    return stream.from_iterable(inputs).pipe_through_channel(channel).run_collect()


def _issue_paths(error: object) -> list[tuple[object, ...]]:
    assert isinstance(error, S.SchemaError)
    return [issue["path"] for issue in make_formatter_standard_schema_v1()(error.issue)["issues"]]


class _Person(TypedDict):
    name: str
    age: float


Person = S.Struct(_Person, age=S.FiniteFromString).pipe(
    S.encode_keys({"name": "Full Name", "age": "Age (years)"})
)


def test_identifies_csv_errors():
    """identifies Csv errors"""
    assert csv.is_csv_error(csv.CsvError("Syntax", "boom", 1, 1))
    assert not csv.is_csv_error({"_tag": "CsvError"})
    assert not csv.is_csv_error(None)


@testing.effect
def test_decodes_records_split_at_every_chunk_boundary():
    """decodes records split at every chunk boundary"""
    text = '\ufeffa,"b,\r\nc"\r\n"d""e",\n\nf\rg\n'
    for i in range(len(text) + 1):
        pieces = [text[:i], text[i:]]
        assert (yield from _run(pieces, csv.decode_string())) == [
            ("a", "b,\r\nc"),
            ('d"e', ""),
            ("",),
            ("f",),
            ("g",),
        ]
        assert (yield from _run(pieces, csv.decode_string(ignore_empty_lines=True))) == [
            ("a", "b,\r\nc"),
            ('d"e', ""),
            ("f",),
            ("g",),
        ]
    assert (yield from _run(['a;"b;c"'], csv.decode_string(delimiter=";"))) == [("a", "b;c")]


@testing.effect
def test_reports_syntax_errors_with_record_line_and_column():
    """reports syntax errors with record, line and column"""
    for text, record, line, column in [
        ('a,b\n"x\ny",c"d\n', 2, 2, 2),
        ('a\n\nb,"c"x', 3, 3, 2),
        ('a,"b', 1, 1, 2),
    ]:
        error = yield from _run([text], csv.decode_string()).flip()
        assert isinstance(error, csv.CsvError)
        assert (error.kind, error.record, error.line, error.column) == (
            "Syntax",
            record,
            line,
            column,
        )


@testing.effect
def test_limits_record_size_across_chunks():
    """limits record size across chunks"""
    assert (yield from _run(["ab", "c", "\n"], csv.decode_string(max_record_size=3))) == [("abc",)]
    boundary = yield from _run(["ab", "c", "d\n"], csv.decode_string(max_record_size=3)).flip()
    assert (boundary.kind, boundary.record, boundary.line) == ("RecordSize", 1, 1)
    error = yield from _run(list("abc\nabcd\n"), csv.decode_string(max_record_size=3)).flip()
    assert (error.kind, error.record, error.line) == ("RecordSize", 2, 2)
    large = "a" * 1_048_577
    assert (yield from _run([large], csv.decode_string()).flip()).kind == "RecordSize"
    assert (yield from _run([large], csv.decode_string(max_record_size=float("inf")))) == [(large,)]


@testing.effect
def test_decodes_header_records_with_fresh_state_per_run():
    """decodes header records with fresh state per run"""
    channel = csv.decode_string(headers=True)
    assert (yield from _run(["a,__proto__\n1,2\n"], channel)) == [{"a": "1", "__proto__": "2"}]
    assert (yield from _run(["b\n3"], channel)) == [{"b": "3"}]
    assert (yield from _run([], channel)) == []
    assert (yield from _run(["a,b\n"], channel)) == []
    for text, record in [("a,a\n1,2", 1), ("a,b\n1,2\n3", 3)]:
        error = yield from _run([text], channel).flip()
        assert (error.kind, error.record, error.column) == ("Header", record, None)


class _Tags(TypedDict):
    tags: tuple[str, ...]


class _Count(TypedDict):
    n: float


class _One(TypedDict):
    kind: str
    tags: str


class _Many(TypedDict):
    kind: str
    tags: tuple[str, ...]


def test_rejects_invalid_options_at_construction():
    """rejects invalid options at construction"""
    for delimiter in ["", ";;", '"', "\n", "\r"]:
        with pytest.raises(ValueError):
            csv.decode_string(delimiter=delimiter)
        with pytest.raises(ValueError):
            csv.encode_string(delimiter=delimiter)
    with pytest.raises(ValueError):
        csv.decode_string(max_record_size=0)
    with pytest.raises(ValueError):
        csv.encode_string(headers=True)  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValueError):
        csv.encode_schema_string(S.Tuple(S.String), headers=True)
    tags = S.Struct(_Tags, tags=S.Array(S.String))
    not_a_string = re.compile(r'column "tags".*not a string')
    with pytest.raises(ValueError, match=not_a_string):
        csv.decode_schema_string(tags, headers=True)
    with pytest.raises(ValueError, match=not_a_string):
        csv.encode_schema_string(tags)
    with pytest.raises(ValueError, match=r'column "n".*not a string'):
        csv.decode_schema_string(S.Struct(_Count), headers=True, disable_codecs=True)
    lazy = S.suspend(lambda: tags)
    with pytest.raises(ValueError, match=not_a_string):
        csv.encode_schema_string(lazy, columns=["tags"])
    tagged = S.Union(
        S.Struct(_One, kind=S.Literal("one")),
        S.Struct(_Many, kind=S.Literal("many"), tags=S.Array(S.String)),
    )
    with pytest.raises(ValueError, match=not_a_string):
        csv.encode_schema_string(tagged, columns=["kind", "tags"])


@testing.effect
def test_encodes_rows_and_header_records():
    """encodes rows and header records"""
    rows = [("",), ("a,b", 'c"d', "e\nf", "g\rh"), ("", " x ")]
    text = "".join((yield from _run(rows, csv.encode_string())))
    assert text == '""\r\n"a,b","c""d","e\nf","g\rh"\r\n, x \r\n'
    assert (yield from _run([text], csv.decode_string())) == rows
    assert (yield from _run([("a;b", "c,d")], csv.encode_string(delimiter=";", newline="\n"))) == [
        '"a;b";c,d\n'
    ]
    for delimiter in ["]", "[", "^", "-", "\\"]:
        assert (
            yield from _run([("a" + delimiter + "b", "c")], csv.encode_string(delimiter=delimiter))
        ) == ['"a' + delimiter + 'b"' + delimiter + "c\r\n"]
    records = [{"a": "1", "b": "2", "c": "ignored"}, {"a": None}, {}]
    written = yield from _run(records, csv.encode_string(columns=["b", "a"], headers=True))
    assert "".join(written) == "b,a\r\n2,1\r\n,\r\n,\r\n"


@testing.effect
def test_decodes_and_encodes_utf_8_bytes():
    """decodes and encodes UTF-8 bytes"""
    data = '"Zoë",東京\r\n"a,b",é\r\n'.encode()
    rows = yield from _run([bytes([byte]) for byte in data], csv.decode())
    assert rows == [("Zoë", "東京"), ("a,b", "é")]
    encoded = yield from _run(rows, csv.encode())
    assert b"".join(encoded).decode() == 'Zoë,東京\r\n"a,b",é\r\n'
    boms = "\ufeff\ufeffa\n".encode()
    assert (yield from _run([boms[0:2], boms[2:4], boms[4:]], csv.decode())) == [("\ufeffa",)]


@testing.effect
def test_decodes_schemas_and_rebases_issue_paths_onto_record_numbers():
    """decodes schemas and rebases issue paths onto record numbers"""
    text = "Full Name,Age (years)\nAlice,32\n\nBob,oops\nCarol,x\n"
    good = csv.decode_schema_string(Person, headers=True, ignore_empty_lines=True)
    assert (yield from _run(["Full Name,Age (years)\nAlice,32\n"], good)) == [
        {"name": "Alice", "age": 32}
    ]
    first = yield from _run([text], good).flip()
    assert _issue_paths(first) == [(4, "age")]
    every = csv.decode_schema_string(Person, headers=True, ignore_empty_lines=True, errors="all")
    assert _issue_paths((yield from _run([text], every).flip())) == [(4, "age"), (5, "age")]


class _Note(TypedDict):
    name: str
    note: NotRequired[str]


class _Positive(TypedDict):
    n: float


@testing.effect
def test_encodes_schemas_with_derived_columns():
    """encodes schemas with derived columns"""
    people = [{"name": "Alice", "age": 32}]
    assert (yield from _run(people, csv.encode_schema_string(Person, headers=True))) == [
        "Full Name,Age (years)\r\n",
        "Alice,32\r\n",
    ]
    assert (yield from _run(people, csv.encode_schema_string(Person))) == ["Alice,32\r\n"]
    channel = csv.encode_schema_string(Person, columns=["Age (years)"], headers=True)
    assert (yield from _run(people, channel)) == ["Age (years)\r\n", "32\r\n"]
    note = S.Struct(_Note)
    assert (yield from _run([{"name": "A"}], csv.encode_schema_string(note))) == ["A,\r\n"]
    positive = S.Struct(_Positive, n=S.NumberFromString.check(S.is_greater_than(0)))
    error = yield from _run([{"n": 1}, {"n": -1}], csv.encode_schema_string(positive)).flip()
    assert _issue_paths(error) == [(2, "n")]


class _Entry(TypedDict):
    n: float
    b: bool
    d: datetime
    score: NotRequired[float]
    note: str


class _Score(TypedDict):
    score: NotRequired[float]


@testing.effect
def test_converts_non_string_columns_with_the_stringtree_codec():
    """converts non-string columns with the StringTree codec"""
    entry = S.Struct(_Entry, d=S.DateTimeUtc)
    text = "n,b,d,score,note\r\n1,true,1970-01-01T00:00:00.000Z,,\r\n"
    entries = yield from _run([text], csv.decode_schema_string(entry, headers=True))
    assert entries == [{"n": 1, "b": True, "d": datetime(1970, 1, 1, tzinfo=UTC), "note": ""}]
    written = yield from _run(entries, csv.encode_schema_string(entry, headers=True))
    assert "".join(written) == text
    lazy = S.suspend(lambda: S.Struct(_Score))
    assert (yield from _run(['score\n""\n'], csv.decode_schema_string(lazy, headers=True))) == [{}]


class _Named(TypedDict):
    name: str
    age: float


@testing.effect
def test_round_trips_tuple_schemas_by_position():
    """round trips tuple schemas by position"""
    tuple_person = S.Tuple(S.String, S.NumberFromString).pipe(
        S.decode_to(
            S.Struct(_Named),
            T.transform(
                decode=lambda pair: {"name": pair[0], "age": pair[1]},
                encode=lambda person: (person["name"], person["age"]),
            ),
        )
    )
    text = yield from _run([{"name": "Alice", "age": 32}], csv.encode_schema_string(tuple_person))
    assert text == ["Alice,32\r\n"]
    assert (yield from _run(text, csv.decode_schema_string(tuple_person))) == [
        {"name": "Alice", "age": 32}
    ]


@testing.effect
def test_fails_with_upstream_errors_without_flushing_a_partial_record():
    """fails with upstream errors without flushing a partial record"""
    error = yield from (
        stream.make('"unfinished')
        .concat(stream.fail("upstream"))
        .pipe_through_channel(csv.decode_string())
        .run_collect()
        .flip()
    )
    assert error == "upstream"


@testing.effect
def test_errors_sizes_and_cells_as_effect_gives_them():
    """(pyfect) printed by Effect 4.1.2 under Node: messages, sizes counted in
    UTF-16 code units, line breaks inside quotes, a leading BOM and empty rows"""
    failures = [
        (
            'a,"b"c',
            csv.decode_string(),
            ("Syntax", "Expected a delimiter or line break after a closing quote", 1, 2),
        ),
        ('a"b', csv.decode_string(), ("Syntax", "Unexpected quote in an unquoted field", 1, 1)),
        ('"a', csv.decode_string(), ("Syntax", "Unterminated quoted field", 1, 1)),
        ("a,b\n1", csv.decode_string(headers=True), ("Header", "Expected 2 cells, got 1", 2, None)),
        ("a,a\n1,1", csv.decode_string(headers=True), ("Header", "Duplicate header name", 1, None)),
        (
            "\U0001f600\U0001f600,b\n",
            csv.decode_string(max_record_size=5),
            ("RecordSize", "CSV record exceeds maxRecordSize of 5", 1, None),
        ),
    ]
    for text, channel, expected in failures:
        error = yield from _run([text], channel).flip()
        assert (error.kind, error.message, error.record, error.column) == expected
    rows = csv.decode_string(max_record_size=4)
    assert (yield from _run(["\U0001f600\U0001f600\n"], rows)) == [("\U0001f600\U0001f600",)]
    text = 'x\r\n"a\r\nb"\r\n"\n"\ny'
    assert (yield from _run([text], csv.decode_string())) == [("x",), ("a\r\nb",), ("\n",), ("y",)]
    assert (yield from _run(["\r\n\r\n"], csv.decode_string())) == [("",), ("",)]
    # A CRLF inside quotes split across chunks is one line break.
    split = yield from _run(['"a\r', '\nb"\nc"x'], csv.decode_string()).flip()
    assert (split.record, split.line, split.column) == (2, 3, 1)
    written = yield from _run([("﻿a", ""), ("",), ()], csv.encode_string())
    assert written == ['"﻿a",\r\n', '""\r\n', "\r\n"]
    with pytest.raises(ValueError, match="columns are required to encode Objects schemas"):
        csv.encode_schema_string(S.Record(S.String, S.String))
    with pytest.raises(ValueError, match="cannot verify string cells for String"):
        csv.encode_schema_string(S.Number, columns=["a"])
