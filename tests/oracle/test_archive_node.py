"""What Effect's ``Tar``, ``Zip`` and ``Xml`` did under Node on the corpus of
``_archive_corpus.py``, including fixtures, truncated and corrupt archives and
path-traversal entries (``archive_oracle.ts`` says how to record it). Not Effect test
titles: found by comparing with Effect.

Effect returns traversal paths as written; ``test_paths_are_returned_as_written`` says
so outright, since that is what callers must guard against. Only ``zlib`` differences
differences are allowed (``DIVERGENCES``, ``docs/PARITY.md`` section 4): which message
of corrupt deflate data is reported depends on the zlib build."""
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import stream, testing
from pyfect.encoding import tar, xml
from pyfect.encoding import zip as Zip
from pyfect.result import Ok

from ._archive_corpus import corpus

ORACLE = json.loads((Path(__file__).parent / "fixtures" / "archive_oracle.json").read_text())
CASES: list[dict[str, Any]] = json.loads(json.dumps(corpus()))
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def unbase64(data: str) -> bytes:
    return base64.b64decode(data)


def digest(data: bytes) -> str:
    return f"{len(data)}:{hashlib.sha256(data).hexdigest()[:16]}"


def date(value: Any) -> datetime | None:
    if value is None:
        return None
    if value == "invalid":
        return datetime(2024, 1, 1)
    return EPOCH + timedelta(milliseconds=value)


def millis(value: datetime | tar.FarDate) -> int:
    if isinstance(value, tar.FarDate):
        return value.epoch_millis
    return (value - EPOCH) // timedelta(milliseconds=1)


def error_of(error: Any) -> dict[str, Any]:
    out = {"kind": error.kind, "message": error.message}
    if isinstance(error, xml.XmlError) and error.line is not None:
        out |= {"line": error.line, "column": error.column}
    return out


def header_of(header: Any) -> dict[str, Any]:
    if isinstance(header, tar.Header):
        return {
            "path": header.path,
            "type": header.type,
            "typeflag": header.typeflag,
            "size": header.size,
            "mode": header.mode,
            "uid": header.uid,
            "gid": header.gid,
            "uname": header.uname,
            "gname": header.gname,
            "mtime": millis(header.mtime),
            "pax": dict(header.pax),
            "linkTarget": header.link_target,
            "devMajor": header.dev_major,
            "devMinor": header.dev_minor,
        }
    return {
        "path": header.path,
        "type": header.type,
        "method": header.method,
        "mtime": millis(header.mtime),
        "size": header.size,
        "mode": header.mode,
        "linkTarget": None,
        "devMajor": None,
        "devMinor": None,
    }


def finish(effect: Any, out: dict[str, Any]) -> dict[str, Any]:
    result = fx.run_blocking_exit(effect)
    if isinstance(result, fx.Failure):
        found = result.cause.find_error()
        if isinstance(found, Ok):
            out["error"] = error_of(found.value)
        else:
            out["die"] = True
    return out


def decode_archive(channel: Any, chunks: list[bytes]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []

    def read(entry: Any) -> Any:
        record: dict[str, Any] = {"header": header_of(entry.header), "body": None}
        items.append(record)

        def done(body: bytes) -> None:
            record["body"] = digest(body)

        return entry.body.run_bytes().map(done)

    effect = (
        stream.from_iterable(chunks, chunk_size=1).pipe_through_channel(channel).map_effect(read)
    )
    return finish(effect.run_drain(), {"items": items, "error": None})


def tar_entry(e: dict[str, Any]) -> Any:
    options: dict[str, Any] = {
        key: e[key] for key in ("mode", "uid", "gid", "uname", "gname", "pax") if key in e
    }
    options["mtime"] = date(e.get("mtime"))
    kind = e["kind"]
    if kind == "file":
        return tar.file(e["path"], e["text"] if "text" in e else unbase64(e["content"]), **options)
    if kind == "stream":
        body = stream.from_iterable([unbase64(c) for c in e["chunks"]])
        return tar.file_stream(e["path"], e["size"], body, **options)
    if kind == "directory":
        return tar.directory(e["path"], **options)
    if kind == "symlink":
        return tar.symlink(e["path"], e["target"], **options)
    if kind == "hardlink":
        return tar.hardlink(e["path"], e["target"], **options)
    entry = tar.file(e["path"], "", **options)
    header = replace(
        entry.header,
        type=e["type"],
        typeflag=e["typeflag"],
        size=e.get("size", 0),
        dev_major=e.get("devMajor"),
        dev_minor=e.get("devMinor"),
    )
    return tar.Entry(header, stream.empty)


def zip_entry(e: dict[str, Any]) -> Any:
    options: dict[str, Any] = {key: e[key] for key in ("method", "mode") if key in e} | {
        "mtime": date(e.get("mtime"))
    }
    kind = e["kind"]
    if kind == "file":
        return Zip.file(e["path"], e["text"] if "text" in e else unbase64(e["content"]), **options)
    if kind == "stream":
        body = stream.from_iterable([unbase64(c) for c in e["chunks"]])
        file_stream: Any = Zip.file_stream
        return file_stream(e["path"], body, size=e.get("size"), **options)
    return Zip.directory(e["path"], **options)


def encode_archive(channel: Any, entries: list[Any]) -> dict[str, Any]:
    chunks: list[bytes] = []

    def keep(chunk: bytes) -> fx.Effect[None]:
        return fx.sync(lambda: chunks.append(chunk))

    source: Any = stream.from_iterable(entries)
    effect = source.pipe_through_channel(channel).run_for_each(keep)
    out = finish(effect, {"error": None})
    out["bytes"] = digest(b"".join(chunks))
    return out


def xml_event(event: Any) -> dict[str, Any]:  # noqa: PLR0911
    match event:
        case xml.Declaration(version, encoding, standalone):
            out: dict[str, Any] = {"_tag": "Declaration", "version": version}
            if encoding is not None:
                out["encoding"] = encoding
            if standalone is not None:
                out["standalone"] = standalone
            return out
        case xml.Doctype(name, public_id, system_id):
            out: dict[str, Any] = {"_tag": "Doctype", "name": name}
            if public_id is not None:
                out["publicId"] = public_id
            if system_id is not None:
                out["systemId"] = system_id
            return out
        case xml.StartElement(name, attributes):
            return {"_tag": "StartElement", "name": name, "attributes": dict(attributes)}
        case xml.EndElement(name):
            return {"_tag": "EndElement", "name": name}
        case xml.Text(text):
            return {"_tag": "Text", "text": text}
        case xml.Comment(text):
            return {"_tag": "Comment", "text": text}
        case xml.ProcessingInstruction(target, data):
            return {"_tag": "ProcessingInstruction", "target": target, "data": data}
        case _:
            raise AssertionError(event)


def to_event(e: dict[str, Any]) -> Any:  # noqa: PLR0911
    match e["_tag"]:
        case "Declaration":
            return xml.Declaration(e["version"], e.get("encoding"), e.get("standalone"))
        case "Doctype":
            return xml.Doctype(e["name"], e.get("publicId"), e.get("systemId"))
        case "StartElement":
            return xml.StartElement(e["name"], e["attributes"])
        case "EndElement":
            return xml.EndElement(e["name"])
        case "Text":
            return xml.Text(e["text"])
        case "Comment":
            return xml.Comment(e["text"])
        case _:
            return xml.ProcessingInstruction(e["target"], e["data"])


def element_of(element: xml.Element) -> dict[str, Any]:
    return {
        "name": element.name,
        "attributes": dict(element.attributes),
        "children": [c if isinstance(c, str) else element_of(c) for c in element.children],
    }


def collect_items(source: Any, channel: Any, item: Any) -> dict[str, Any]:
    items: list[Any] = []

    def keep(value: Any) -> fx.Effect[None]:
        return fx.sync(lambda: items.append(item(value)))

    effect = source.pipe_through_channel(channel).run_for_each(keep)
    return finish(effect, {"items": items, "error": None})


def decode_xml(source: Any, channel: Any) -> dict[str, Any]:
    items: list[dict[str, Any]] = []

    def keep(event: Any) -> fx.Effect[None]:
        return fx.sync(lambda: items.append(xml_event(event)))

    effect = source.pipe_through_channel(channel).run_for_each(keep)
    return finish(effect, {"items": items, "error": None})


def xml_options(case: dict[str, Any]) -> dict[str, int]:
    options = case.get("options", {})
    out: dict[str, int] = {}
    if "maxDepth" in options:
        out["max_depth"] = options["maxDepth"]
    if "maxTokenSize" in options:
        out["max_token_size"] = options["maxTokenSize"]
    return out


def run(case: dict[str, Any]) -> dict[str, Any]:  # noqa: PLR0911
    chunks = [unbase64(chunk) for chunk in case.get("chunks", [])]
    match case["op"]:
        case "tar.decode":
            return decode_archive(tar.decode(), chunks)
        case "zip.decode":
            return decode_archive(Zip.decode(), chunks)
        case "tar.encode":
            return encode_archive(tar.encode(), [tar_entry(e) for e in case["entries"]])
        case "zip.encode":
            return encode_archive(Zip.encode(), [zip_entry(e) for e in case["entries"]])
        case "xml.decode":
            source = stream.from_iterable(chunks, chunk_size=1)
            return decode_xml(source, xml.decode(**xml_options(case)))
        case "xml.decodeString":
            source = stream.from_iterable(case["strings"], chunk_size=1)
            return decode_xml(source, xml.decode_string(**xml_options(case)))
        case "xml.elements":
            source = stream.from_iterable([to_event(e) for e in case["events"]], chunk_size=1)
            limit = case["options"].get("maxElementSize")
            return collect_items(
                source, xml.elements(case["path"], max_element_size=limit), element_of
            )
        case "xml.encodeString":
            source = stream.from_iterable([to_event(e) for e in case["events"]])
            return collect_items(source, xml.encode_string(), str)
        case op:
            raise AssertionError(op)


DIVERGENCES: dict[str, dict[str, Any]] = {
    # zlib takes a code length code without symbols, and fails when it next reads
    # enough input, which this archive does not have
    "zip.decode/deflate/invalid/dynamic-incomplete": {
        "items": [{"body": None}],
        "kind": "Truncated",
    },
}


def normalized(result: dict[str, Any]) -> dict[str, Any]:
    """Without the wording of zlib's errors."""
    error = result.get("error")
    if error is not None and error["kind"] == "InvalidData":
        return {**result, "error": {"kind": "InvalidData"}}
    return result


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_matches_effect(case: dict[str, Any]) -> None:
    id_ = case["id"].removesuffix("#7")
    result = run(case)
    if id_ in DIVERGENCES:
        expected = DIVERGENCES[id_]
        assert result["error"]["kind"] == expected["kind"]
        assert [item["body"] for item in result["items"]] == [
            item["body"] for item in expected["items"]
        ]
        return
    assert normalized(result) == normalized(ORACLE[case["id"]])


@testing.effect
def test_paths_are_returned_as_written() -> Any:
    """As in Effect: neither decoder rejects or rewrites a path that leaves the
    target directory, and neither ``encode`` rejects ``..`` segments."""
    for op, path in (("tar.decode", "../../etc/passwd"), ("tar.decode", "/etc/passwd")):
        assert (
            ORACLE[f"{op}/traversal/{'dotdot' if '..' in path else 'absolute'}"]["items"][0][
                "header"
            ]["path"]
            == path
        )
    symlink = ORACLE["tar.decode/traversal/symlink-then-write"]["items"]
    assert [(i["header"]["path"], i["header"]["linkTarget"]) for i in symlink] == [
        ("out", "/etc"),
        ("out/passwd", None),
    ]
    for name, path in (("dotdot", "../../etc/passwd"), ("absolute", "/etc/passwd")):
        assert ORACLE[f"zip.decode/traversal/{name}"]["items"][0]["header"]["path"] == path
    assert ORACLE["tar.encode/traversal"]["error"] is None
    assert ORACLE["zip.encode/traversal"]["error"] is None
    yield from fx.void


def test_other_readers_read_what_encode_writes() -> None:
    """Python's ``tarfile`` and ``zipfile``, which read the central directory."""
    big = bytes(i % 251 for i in range(100_000))
    tar_items: Any = stream.from_iterable(
        [
            tar.directory("d"),
            tar.file("d/a", b"hello"),
            tar.symlink("d/l", "a"),
            tar.file("b" * 200, big),
        ]
    )
    data = fx.run_blocking(tar_items.pipe_through_channel(tar.encode()).run_bytes())
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        assert archive.getnames() == ["d", "d/a", "d/l", "b" * 200]
        member = archive.extractfile("b" * 200)
        assert member is not None
        assert member.read() == big

    zip_items: Any = stream.from_iterable(
        [
            Zip.directory("d"),
            Zip.file("d/a", b"hello"),
            Zip.file("s", big, method="Store"),
            Zip.file_stream("f", stream.make(big[:70_000], big[70_000:])),
            Zip.file_stream("g", stream.make(big), size=len(big)),
        ]
    )
    data = fx.run_blocking(zip_items.pipe_through_channel(Zip.encode()).run_bytes())
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == ["d/", "d/a", "s", "f", "g"]
        assert [archive.read(n) for n in ("s", "f", "g")] == [big, big, big]
