"""Ports of Effect's ``http/Multipart.test.ts``.

Each test's docstring is the Effect test title. A Web ``Response`` of a
``FormData`` is the form's multipart encoding (``_form_data.encode``) and
``FileSystem.makeNoop`` is a ``NoopFileSystem`` subclass.
"""

from collections.abc import Callable
from typing import Any, Never, TypedDict

import pytest

import pyfect as fx
from pyfect import effect, error_reporter, schema, sink, stream
from pyfect.byte_size import ByteSize
from pyfect.exit import Failure, Success
from pyfect.file_system import FileSystem, NoopFileSystem
from pyfect.http import _form_data
from pyfect.http import body as http_body
from pyfect.http import multipart as m
from pyfect.http import multipart_parser as mp
from pyfect.http import request as client_request
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.server_request import from_client_request
from pyfect.http.server_respondable import to_response
from pyfect.path import layer as path_layer
from pyfect.platform_error import PlatformError
from pyfect.scope import Scope, scoped
from pyfect.sink import Sink

BOUNDARY = "----testboundary"
HEADERS = {"content-type": f"multipart/form-data; boundary={BOUNDARY}"}


def _parts(
    chunks: stream.Stream[bytes, Any], headers: dict[str, str]
) -> stream.Stream[m.Part, Any]:
    return chunks.pipe_through_channel(m.make_channel(headers))


def _error(eff: fx.Effect[Any, Any]) -> object:
    exit = fx.run_blocking_exit(eff)
    assert isinstance(exit, Failure)
    return exit.cause.squash()


def _value[A](eff: fx.Effect[A, Any]) -> A:
    exit = fx.run_blocking_exit(eff)
    assert isinstance(exit, Success), exit
    return exit.value


class _Value(TypedDict):
    value: str


def test_schema_json_applies_a_json_reviver() -> None:
    """schemaJson applies a JSON reviver"""
    decode = m.schema_json(
        schema.Struct(_Value),
        reviver=lambda key, value: "revived" if key == "value" else value,
    )
    assert _value(decode({"json": '{"value":"original"}'}, "json")) == {"value": "revived"}


def _encoded(form: http_body.FormData) -> tuple[stream.Stream[bytes], dict[str, str]]:
    data, content_type = _form_data.encode(form)
    return stream.make(data), {"content-type": content_type}


def test_parses_fields_and_streams_file_content_as_stream_parts() -> None:
    """parses fields and streams file content as stream parts"""
    form = (
        http_body.FormData()
        .append("foo", "bar")
        .append("test", "ing")
        .append("file", http_body.File(b"A" * 1024 * 1024, "foo.txt", "text/plain"))
    )
    chunks, headers = _encoded(form)
    streamed: list[m.Part] = []

    def each(part: m.Part) -> fx.Effect[tuple[str, str], Any]:
        streamed.append(part)
        if isinstance(part, m.File):
            return m.collect_bytes(part.content).map(lambda data: (part.name, data.decode()))
        return effect.succeed((part.key, part.value))

    parts = _value(_parts(chunks, headers).map_effect(each).run_collect())
    assert list(parts) == [("foo", "bar"), ("test", "ing"), ("foo.txt", "A" * 1024 * 1024)]
    assert [(m.is_part(p), m.is_stream_part(p)) for p in streamed] == [(True, True)] * 3


def _file_contents(part: m.Part) -> fx.Effect[bytes, Any]:
    if isinstance(part, m.File):
        return part.content_effect
    return effect.die(AssertionError("expected file"))


def test_collects_file_content_across_pulls_and_a_split_trailing_boundary() -> None:
    """collects file content across pulls and a split trailing boundary"""
    split = 8
    chunks = [
        (
            f"--{BOUNDARY}\r\n"
            'Content-Disposition: form-data; name="file"; filename="file.txt"\r\n'
            "Content-Type: text/plain\r\n\r\nabc"
        ).encode(),
        f"def\r\n--{BOUNDARY[:split]}".encode(),
        f"{BOUNDARY[split:]}--\r\n".encode(),
    ]
    source = stream.from_iterable(chunks).rechunk(1)
    contents = _value(_parts(source, HEADERS).map_effect(_file_contents).run_collect())
    assert list(contents) == [b"abcdef"]


def test_emits_a_field_buffered_while_reading_a_file_without_pulling_more_input() -> None:
    """emits a field buffered while reading a file without pulling more input"""
    body = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="file"; filename="file.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "file contents\r\n"
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="description"\r\n\r\n'
        "test file\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()
    chunks = [body[:64], body[64:128], body[128:]]
    source = stream.from_iterable(chunks).rechunk(1).concat(stream.never)

    def each(part: m.Part) -> fx.Effect[tuple[str, str], Any]:
        if isinstance(part, m.File):
            return part.content_effect.map(lambda data: (part.key, data.decode()))
        return effect.succeed((part.key, part.value))

    parts = _value(_parts(source, HEADERS).map_effect(each).take(2).run_collect().timeout(2))
    assert list(parts) == [("file", "file contents"), ("description", "test file")]


def test_parses_non_latin_1_filenames() -> None:
    """parses non-Latin-1 filenames"""
    form = http_body.FormData().append(
        "file", http_body.File(b"content", "日本語.txt", "text/plain")
    )
    chunks, headers = _encoded(form)

    def each(part: m.Part) -> fx.Effect[tuple[str, str], Any]:
        if isinstance(part, m.File):
            return part.content.run_drain().as_((part.key, part.name))
        return effect.succeed((part.key, part.value))

    assert list(_value(_parts(chunks, headers).map_effect(each).run_collect())) == [
        ("file", "日本語.txt")
    ]


def _file_part(name: str) -> str:
    return (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="{name}"; filename="{name}.txt"\r\n'
        f"Content-Type: text/plain\r\n\r\n{name}\r\n"
    )


def test_fails_when_a_limit_is_exceeded_even_if_the_whole_body_arrives_in_one_chunk() -> None:
    """fails when a limit is exceeded even if the whole body arrives in one chunk"""
    body = _file_part("a") + _file_part("b") + _file_part("c") + f"--{BOUNDARY}--\r\n"
    error = _error(
        _parts(stream.make(body.encode()), HEADERS)
        .run_collect()
        .pipe(effect.provide_service(m.MaxParts, 2))
    )
    assert isinstance(error, m.MultipartError)
    assert error.reason.tag == "TooManyParts"


_FILE_START = (
    f"--{BOUNDARY}\r\n"
    'Content-Disposition: form-data; name="file"; filename="file.txt"\r\n'
    "Content-Type: text/plain\r\n\r\na"
)
_FILE_END = f"\r\n--{BOUNDARY}--\r\n"


def _drain_files(
    chunks: list[str], provide: Callable[[fx.Effect[None, Any]], fx.Effect[None, Any]]
) -> tuple[int, object]:
    file_parts = 0

    def each(part: m.Part) -> fx.Effect[None, Any]:
        nonlocal file_parts
        if not isinstance(part, m.File):
            return effect.void
        file_parts += 1
        return part.content.run_drain()

    source = stream.from_iterable([chunk.encode() for chunk in chunks])
    error = _error(provide(_parts(source, HEADERS).map_effect(each).run_drain()))
    return file_parts, error


def test_propagates_file_too_large_after_a_file_exceeds_the_limit_mid_stream() -> None:
    """propagates FileTooLarge after a file exceeds the limit mid-stream"""
    file_parts, error = _drain_files(
        [_FILE_START, "a" * 1024, _FILE_END],
        lambda eff: eff.pipe(effect.provide_service(m.MaxFileSize, ByteSize(256))),
    )
    assert file_parts == 1
    assert isinstance(error, m.MultipartError)
    assert error.reason.tag == "FileTooLarge"


def test_propagates_body_too_large_after_the_total_size_limit_is_exceeded_mid_file() -> None:
    """propagates BodyTooLarge after the total size limit is exceeded mid-file"""
    file_parts, error = _drain_files(
        [_FILE_START, "a" * 1024, _FILE_END],
        lambda eff: eff.pipe(effect.provide_service(MaxBodySize, ByteSize(256))),
    )
    assert file_parts == 1
    assert isinstance(error, m.MultipartError)
    assert error.reason.tag == "BodyTooLarge"


def _active_file_parts(error: m.MultipartError) -> stream.Stream[m.Part, m.MultipartError]:
    head = b'--b\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n\r\nhello'
    source: stream.Stream[bytes, m.MultipartError] = stream.make(head).concat(stream.fail(error))
    return _parts(source, {"content-type": "multipart/form-data; boundary=b"})


def _upstream_error() -> m.MultipartError:
    return m.MultipartError.from_reason("InternalError", RuntimeError("body-read-failed"))


def test_propagates_upstream_failure_while_consuming_an_active_file() -> None:
    """propagates upstream failure while consuming an active file"""
    upstream = _upstream_error()
    bytes_read = 0

    def count(chunk: bytes) -> fx.Effect[None]:
        nonlocal bytes_read
        bytes_read += len(chunk)
        return effect.void

    def each(part: m.Part) -> fx.Effect[None, Any]:
        if isinstance(part, m.File):
            return part.content.run_for_each(count).flat_map(
                lambda _: effect.die(AssertionError("content should have failed"))
            )
        return effect.die(AssertionError("expected file"))

    error = _error(_active_file_parts(upstream).run_for_each(each).timeout(1))
    assert bytes_read == 5
    assert error is upstream


def test_preserves_upstream_failure_when_collecting_an_active_file_with_content_effect() -> None:
    """preserves upstream failure when collecting an active file with contentEffect"""
    upstream = _upstream_error()

    def each(part: m.Part) -> fx.Effect[None, Any]:
        if isinstance(part, m.File):
            return part.content_effect.flat_map(
                lambda _: effect.die(AssertionError("contentEffect should have failed"))
            )
        return effect.die(AssertionError("expected file"))

    error = _error(_active_file_parts(upstream).run_for_each(each).timeout(1))
    assert error is upstream


def _ignore(_chunk: bytes) -> None:
    return None


class _TempFileSystem(NoopFileSystem):
    def __init__(self, on_chunk: Callable[[bytes], None] | None = None) -> None:
        self._on_chunk = on_chunk

    def make_temp_directory_scoped(
        self, *, directory: str | None = None, prefix: str = ""
    ) -> fx.Effect[str, PlatformError, Scope]:
        return effect.succeed("/tmp/audit")

    def sink(
        self, path: str, *, flag: Any = "w", mode: int = 0o666
    ) -> Sink[None, bytes, Never, PlatformError]:
        on_chunk: Callable[[bytes], None] = self._on_chunk or _ignore

        def each(chunk: bytes) -> fx.Effect[None]:
            on_chunk(chunk)
            return effect.void

        return sink.for_each(each)


def _persist[A](eff: fx.Effect[A, Any, Any], file_system: NoopFileSystem) -> fx.Effect[A, Any]:
    provided: fx.Effect[A, Any, Any] = eff.pipe(effect.provide_service(FileSystem, file_system))
    return scoped(provided.pipe(fx.provide(path_layer)))


def test_preserves_the_upstream_error_cause_when_persisting_an_active_file() -> None:
    """preserves the upstream error cause when persisting an active file"""
    upstream = _upstream_error()
    bytes_written = 0

    def written(chunk: bytes) -> None:
        nonlocal bytes_written
        bytes_written += len(chunk)

    error = _error(
        _persist(m.to_persisted(_active_file_parts(upstream)), _TempFileSystem(written)).timeout(1)
    )
    assert bytes_written == 5
    assert error is upstream


def test_propagates_parse_when_the_body_ends_mid_file() -> None:
    """propagates Parse when the body ends mid-file"""
    file_parts, error = _drain_files([_FILE_START, "bbbb"], lambda eff: eff)
    assert file_parts == 1
    assert isinstance(error, m.MultipartError)
    assert error.reason.tag == "Parse"


@pytest.mark.parametrize(
    ("description", "options", "limit", "expected_fields"),
    [
        ("maxParts", {"max_parts": 2}, "MaxParts", ["a", "b"]),
        ("maxFieldSize", {"max_field_size": "1 B"}, "MaxFieldSize", []),
        ("maxPartSize", {"max_part_size": ByteSize(1)}, "MaxPartSize", []),
    ],
)
def test_stops_delivering_fields_when_a_limit_is_exceeded(
    description: str, options: dict[str, Any], limit: str, expected_fields: list[str]
) -> None:
    """stops delivering fields when $description is exceeded"""
    fields: list[str] = []
    errors: list[mp.MultipartError] = []
    parser = mp.make(
        headers=HEADERS,
        on_field=lambda info, _value: fields.append(info.name),
        on_file=lambda _info: lambda _chunk: None,
        on_error=errors.append,
        on_done=lambda: None,
        **options,
    )

    def part(name: str) -> str:
        return f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\nvalue\r\n'

    parser.write((part("a") + part("b") + part("c") + part("d") + f"--{BOUNDARY}--\r\n").encode())
    parser.end()
    assert errors == [mp.ReachedLimit(limit)]  # pyright: ignore[reportArgumentType]
    assert fields == expected_fields


@pytest.mark.parametrize(
    ("disposition", "expected"),
    [
        ("filename*=UTF-8'en'%E2%82%AC.txt", [("file", "€.txt")]),
        ("filename*=iso-8859-1''%E4.txt", [("file", "ä.txt")]),
        ("filename*=UTF-8''%E2%82%AC.txt; filename=\"fallback.txt\"", [("file", "€.txt")]),
        ("filename=my file.txt", [("error", "InvalidDisposition")]),
        ("filename*=UTF-8''%ZZ.txt", [("error", "InvalidDisposition")]),
        ('\tfilename = "file.txt"', [("file", "file.txt")]),
        ('filename="first.txt"; FILENAME="second.txt"', [("error", "InvalidDisposition")]),
        ('filename="a\tb\\\tc.txt"', [("file", "a\tb\\\tc.txt")]),
    ],
)
def test_parses_content_disposition_parameters(
    disposition: str, expected: list[tuple[str, str | None]]
) -> None:
    """parses Content-Disposition parameters: $disposition"""
    events: list[tuple[str, str | None]] = []

    def on_file(info: mp.PartInfo) -> mp.OnChunk:
        events.append(("file", info.filename))
        return lambda _chunk: None

    parser = mp.make(
        headers=HEADERS,
        on_field=lambda info, _value: events.append(("field", info.name)),
        on_file=on_file,
        on_error=lambda error: events.append(("error", error.tag)),
        on_done=lambda: None,
    )
    parser.write(
        (
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="upload"; {disposition}\r\n\r\n'
            f"content\r\n--{BOUNDARY}--\r\n"
        ).encode()
    )
    parser.end()
    assert events == expected


def test_parses_tabs_in_quoted_content_type_parameters() -> None:
    """parses tabs in quoted Content-Type parameters"""
    events: list[tuple[str, str | None]] = []

    def on_file(info: mp.PartInfo) -> mp.OnChunk:
        events.append((info.content_type, info.content_type_parameters.get("x")))
        return lambda _chunk: None

    parser = mp.make(
        headers=HEADERS,
        on_field=lambda _info, _value: None,
        on_file=on_file,
        on_error=lambda error: events.append(("error", error.tag)),
        on_done=lambda: None,
    )
    parser.write(
        (
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="upload"; filename="a.txt"\r\n'
            f'Content-Type: text/plain; x="a\tb\\\tc"\r\n\r\ncontent\r\n--{BOUNDARY}--\r\n'
        ).encode()
    )
    parser.end()
    assert events == [("text/plain", "a\tb\tc")]


def test_handles_the_final_boundary_delimiter_split_between_the_trailing_hyphens() -> None:
    """handles the final boundary delimiter split between the trailing hyphens"""
    errors: list[mp.MultipartError] = []
    fields: list[tuple[str, str]] = []
    done: list[bool] = []
    parser = mp.make(
        headers=HEADERS,
        max_total_size=float("inf"),
        max_part_size=float("inf"),
        max_field_size=float("inf"),
        on_field=lambda info, value: fields.append((info.name, value.decode())),
        on_file=lambda _info: lambda _chunk: None,
        on_error=errors.append,
        on_done=lambda: done.append(True),
    )
    body = f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="field"\r\n\r\nvalue'
    parser.write(f"{body}\r\n--{BOUNDARY}-".encode())
    parser.write(b"-\r\n")
    assert done == [True]
    parser.end()
    assert fields == [("field", "value")]
    assert errors == []


def _form_request(form: http_body.FormData) -> stream.Stream[m.Part, m.MultipartError]:
    request = from_client_request(client_request.post("https://example.com").body_form_data(form))
    return request.multipart_stream


def _record_writes(writes: list[str]) -> m.WriteFile:
    def write(path: str, _file: m.File) -> fx.Effect[None]:
        writes.append(path)
        return effect.void

    return write


def test_returns_distinct_persisted_file_paths_as_non_stream_parts() -> None:
    """returns distinct persisted file paths as non-stream parts"""
    form = (
        http_body.FormData()
        .append("first", http_body.File(b"one", "same.txt"))
        .append("second", http_body.File(b"two", "same.txt"))
    )
    writes: list[str] = []
    persisted = _value(
        _persist(m.to_persisted(_form_request(form), _record_writes(writes)), _TempFileSystem())
    )
    first_files = persisted["first"]
    second_files = persisted["second"]
    assert isinstance(first_files, list) and isinstance(second_files, list)
    first, second = first_files[0], second_files[0]
    assert isinstance(first, m.PersistedFile) and isinstance(second, m.PersistedFile)
    assert m.is_persisted_file(first)
    assert m.is_part(first)
    assert not m.is_stream_part(first)
    assert first.path == "/tmp/audit/same.txt"
    assert first.path != second.path
    assert writes == [first.path, second.path]


def test_persists_dot_and_long_multi_byte_file_names_inside_the_temporary_directory() -> None:
    """persists dot and long multi-byte file names inside the temporary directory"""
    names = [".", "..", "文" * 90 + ".pdf"]
    form = http_body.FormData()
    for name in names:
        form = form.append("file", http_body.File(b"content", name))
    persisted = _value(
        _persist(m.to_persisted(_form_request(form), _record_writes([])), _TempFileSystem())
    )
    files = persisted["file"]
    assert isinstance(files, list)
    persisted_files = [file for file in files if isinstance(file, m.PersistedFile)]
    assert [file.name for file in persisted_files] == names
    assert persisted_files[2].path.endswith(".pdf")
    for file in persisted_files:
        directory, _, base = file.path.rpartition("/")
        assert directory == "/tmp/audit"
        assert len(base.encode()) <= 128


@pytest.mark.parametrize(
    ("reason", "status"),
    [
        ("FileTooLarge", 413),
        ("FieldTooLarge", 413),
        ("BodyTooLarge", 413),
        ("TooManyParts", 413),
        ("InternalError", 500),
        ("Parse", 400),
    ],
)
def test_responds_based_on_the_reason_and_is_ignored_by_the_error_reporter(
    reason: m.MultipartErrorTag, status: int
) -> None:
    """responds based on the reason and is ignored by the ErrorReporter"""
    error = m.MultipartError.from_reason(reason)
    assert _value(to_response(error)).status == status
    assert error_reporter.is_ignored(error)


def test_file_schema_to_json_schema() -> None:
    """FileSchema toJsonSchema"""
    document = schema.to_json_schema_document(m.PersistedFileSchema)
    assert document.dialect == "draft-2020-12"
    assert document.definitions == {}
    assert document.schema == (
        {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "name": {"type": "string"},
                "contentType": {"type": "string", "contentEncoding": "binary"},
                "path": {"type": "string"},
            },
            "required": ["key", "name", "contentType", "path"],
            "additionalProperties": True,
        }
    )


def test_identifies_multipart_errors() -> None:
    """identifies multipart errors"""
    assert m.is_multipart_error(m.MultipartError.from_reason("Parse"))
    assert not m.is_multipart_error({"_tag": "MultipartError"})
    assert not m.is_multipart_error(None)
