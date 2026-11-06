"""Ports of Effect's ``encoding/Xml.test.ts``.

Each test's docstring is the Effect test title. Events are frozen dataclasses
(``Effect``'s ``_tag`` is the class), ``Stream.mkString`` is ``run_string`` and
``Uint8Array`` is ``bytes``. Line, column and limit positions count UTF-16 code
units as Effect's do; ``_splits`` splits at every UTF-16 index, as ``split("")``
does, so a chunk can end in half a surrogate pair.

Adapted, with the reason:

- "does not expose inherited attribute values": a ``dict`` inherits nothing, so
  it checks that the absent keys are absent and ``__proto__`` is ordinary.
- "rejects invalid options at construction" raises ``ValueError``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import Any

import pytest

import pyfect as fx
from pyfect import channel, stream, testing
from pyfect.encoding import xml
from pyfect.encoding.xml import (
    Comment,
    Declaration,
    Doctype,
    Element,
    EndElement,
    Event,
    ProcessingInstruction,
    StartElement,
    Text,
    XmlError,
)
from pyfect.result import Err, Ok

BOM = "﻿"


def start(name: str, attributes: dict[str, str] | None = None) -> StartElement:
    return StartElement(name, attributes or {})


end = EndElement
text = Text
comment = Comment
pi = ProcessingInstruction


def decode_string(chunks: list[str], **options: Any) -> fx.Effect[list[Event], XmlError]:
    return (
        stream.from_iterable(chunks, chunk_size=1)
        .pipe_through_channel(xml.decode_string(**options))
        .run_collect()
    )


def decode_bytes(chunks: list[bytes], **options: Any) -> fx.Effect[list[Event], XmlError]:
    return (
        stream.from_iterable(chunks, chunk_size=1)
        .pipe_through_channel(xml.decode(**options))
        .run_collect()
    )


def encode_string(events: list[Event]) -> fx.Effect[str, XmlError]:
    return stream.from_iterable(events).pipe_through_channel(xml.encode_string()).run_string()


def elements(document: str, path: list[str], **options: Any) -> fx.Effect[list[Element], XmlError]:
    return (
        stream.make(document)
        .pipe_through_channel(xml.decode_string())
        .pipe_through_channel(xml.elements(path, **options))
        .run_collect()
    )


def failure(effect: fx.Effect[Any, XmlError]) -> Any:
    def position(error: XmlError) -> tuple[str, int | None, int | None]:
        return (error.kind, error.line, error.column)

    return effect.flip().map(position)


def _units(value: str) -> list[str]:
    """``value.split("")``: UTF-16 code units, a surrogate pair as two strings."""
    out: list[str] = []
    for char in value:
        code = ord(char)
        if code > 0xFFFF:
            code -= 0x10000
            out += [chr(0xD800 + (code >> 10)), chr(0xDC00 + (code & 0x3FF))]
        else:
            out.append(char)
    return out


def splits(value: str) -> Iterator[list[str]]:
    units = _units(value)
    yield units
    for i in range(len(units) + 1):
        yield ["".join(units[:i]), "".join(units[i:])]


def byte_splits(value: bytes) -> Iterator[list[bytes]]:
    yield [bytes((byte,)) for byte in value]
    for i in range(len(value) + 1):
        yield [value[:i], value[i:]]


def test_identifies_xml_errors() -> None:
    """identifies Xml errors"""
    assert xml.is_xml_error(XmlError("Syntax", "boom"))
    assert not xml.is_xml_error({"_tag": "XmlError"})
    assert not xml.is_xml_error(None)


@testing.effect
def test_decodes_documents_split_at_every_index_with_fresh_state_per_run() -> Any:
    """decodes documents split at every index with fresh state per run"""
    document = (
        BOM
        + """<?xml version='1.1' encoding="UTF-8" standalone="no" ?>
<!-- prolog --><?a?>
<feed xmlns:e="urn:e" lang = 'en'>😀<br />
<e:item
  x="1"></e:item><!--inner--><?pi  data ?>
</feed>
<?xml-stylesheet d?>
"""
    )
    expected: list[Event] = [
        Declaration("1.1", "UTF-8", False),
        comment(" prolog "),
        pi("a", ""),
        start("feed", {"xmlns:e": "urn:e", "lang": "en"}),
        text("😀"),
        start("br"),
        end("br"),
        text("\n"),
        start("e:item", {"x": "1"}),
        end("e:item"),
        comment("inner"),
        pi("pi", "data "),
        text("\n"),
        end("feed"),
        pi("xml-stylesheet", "d"),
    ]
    for chunks in splits(document):
        assert (yield from decode_string(chunks)) == expected
    decoder = xml.decode_string()

    def run(value: str) -> Any:
        return stream.make(value).pipe_through_channel(decoder).run_collect()

    assert (yield from run("<a/>")) == [start("a"), end("a")]
    assert (yield from run("<b/>")) == [start("b"), end("b")]


@testing.effect
def test_does_not_expose_inherited_attribute_values() -> Any:
    """does not expose inherited attribute values"""
    events = yield from decode_string(
        ["<a><b id='1'/><c __proto__='literal' constructor='own'/></a>"]
    )
    attributes = [event.attributes for event in events if isinstance(event, StartElement)]
    for absent in attributes[:2]:
        assert "constructor" not in absent
        assert "toString" not in absent
        assert "__proto__" not in absent
    assert attributes[2]["__proto__"] == "literal"
    assert attributes[2]["constructor"] == "own"


@testing.effect
def test_decodes_character_data_and_attribute_values() -> Any:
    """decodes character data and attribute values"""
    document = (
        '<a>p<b c="x\ty\r\nz&#10;&#9;&quot;]]>" __proto__=\'&apos;"\'/>'
        "&lt;&gt;&amp;&apos;&quot;&#65;&#x42;\r\n\r&#13;<![CDATA[<y>&amp;\r]]]]>\r\nz"
        "<!--c--><![CDATA[]]></a>"
    )
    for chunks in splits(document):
        assert (yield from decode_string(chunks)) == [
            start("a"),
            text("p"),
            start("b", {"c": 'x y z\n\t"]]>', "__proto__": "'\""}),
            end("b"),
            text("<>&'\"AB\n\n\r<y>&amp;\n]]\nz"),
            comment("c"),
            end("a"),
        ]


@testing.effect
def test_decodes_doctypes_without_expanding_entities() -> Any:
    """decodes DOCTYPEs without expanding entities"""
    doctype = """<!DOCTYPE a PUBLIC " -//A//B  C " "a[1]>.dtd" [
<!ELEMENT a (#PCDATA|b)*><!ATTLIST a b CDATA 'x' c (y|z) #IMPLIED><!NOTATION n PUBLIC 'n'>
<!ENTITY e "]>"><!ENTITY f SYSTEM "file:///etc/passwd"><!ENTITY g "&e;&f;">
<!ENTITY % p '<!ENTITY q "">'>%p;<!-- ]> --><?p ]>?>]>"""
    for chunks in splits(doctype + "<a/>"):
        assert (yield from decode_string(chunks)) == [
            Doctype("a", "-//A//B C", "a[1]>.dtd"),
            start("a"),
            end("a"),
        ]
    assert (yield from failure(decode_string([doctype + "\n<a>&g;</a>"]))) == ("Unsupported", 5, 4)
    assert (yield from decode_string(["<!DOCTYPE r SYSTEM 'r.dtd'><r/>"])) == [
        Doctype("r", None, "r.dtd"),
        start("r"),
        end("r"),
    ]
    for chunks in splits("<!DOCTYPE a [text]><a/>"):
        assert (yield from decode_string(chunks)) == [Doctype("a"), start("a"), end("a")]
    for chunks in splits("<!DOCTYPE a [>]><a/>"):
        assert (yield from failure(decode_string(chunks))) == ("Syntax", 1, 14)


@testing.effect
def test_decodes_utf_8_bytes() -> Any:
    """decodes UTF-8 bytes"""
    encoded = (BOM + '<名前 é="日本">😀 &#x1F600;</名前>').encode()
    for chunks in byte_splits(encoded):
        assert (yield from decode_bytes(chunks)) == [
            start("名前", {"é": "日本"}),
            text("😀 😀"),
            end("名前"),
        ]
    invalid: list[tuple[bytes, int, int]] = [
        (b"\xfe", 1, 1),
        (b"\xff", 1, 1),
        (b"\xfe\x00", 1, 1),
        (b"\xff\x00", 1, 1),
        (b"<1\xff></a>", 1, 2),
        (b"<1\xe2", 1, 2),
        ("<a>\né".encode() + b"\xff</a>", 2, 2),
        (b"<a>\xed\xa0\x80</a>", 1, 4),
        ("<a/>€".encode()[:-1], 1, 5),
        ("<a>é日本￾</a>".encode(), 1, 7),
        ("<a>😀\x01</a>".encode(), 1, 6),
    ]
    for value, line, column in invalid:
        for chunks in byte_splits(value):
            assert (yield from failure(decode_bytes(chunks))) == ("Syntax", line, column), chunks
    latin1 = '<?xml version="1.0" encoding="ISO-8859-1"?><a/>'
    assert (yield from failure(decode_bytes([latin1.encode()]))) == ("Unsupported", 1, 1)
    assert (yield from decode_string([latin1]))[0] == Declaration("1.0", "ISO-8859-1")


@testing.effect
def test_rejects_utf_16_byte_order_marks_as_unsupported_across_chunk_boundaries() -> Any:
    """rejects UTF-16 byte order marks as unsupported across chunk boundaries"""
    for value in (
        bytes((0xFF, 0xFE, 0x3C, 0, 0x61, 0, 0x2F, 0, 0x3E, 0)),
        bytes((0xFE, 0xFF, 0, 0x3C, 0, 0x61, 0, 0x2F, 0, 0x3E)),
    ):
        for chunks in byte_splits(value):
            assert (yield from failure(decode_bytes(chunks))) == ("Unsupported", 1, 1)


@testing.effect
def test_decodes_ascii_bytes_under_a_us_ascii_declaration() -> Any:
    """decodes ASCII bytes under a US-ASCII declaration"""
    value = b'<?xml version="1.0" encoding="US-ASCII"?><a>ASCII &#233;</a>'
    for chunks in [[value], *byte_splits(value)]:
        assert (yield from decode_bytes(chunks)) == [
            Declaration("1.0", "US-ASCII"),
            start("a"),
            text("ASCII é"),
            end("a"),
        ]


@pytest.mark.parametrize("chunked", [False, True])
@testing.effect
def test_rejects_non_ascii_bytes_under_a_us_ascii_declaration(chunked: bool) -> Any:
    """rejects non-ASCII bytes under a US-ASCII declaration (whole)
    rejects non-ASCII bytes under a US-ASCII declaration (chunked)"""
    value = '<?xml version="1.0" encoding="US-ASCII"?><a>é</a>'.encode()
    for chunks in byte_splits(value) if chunked else [[value]]:
        assert (yield from decode_bytes(chunks).flip()).kind == "Syntax"


@testing.effect
def test_fails_on_malformed_documents_with_positions() -> Any:
    """fails on malformed documents with positions"""
    cases = [
        ("", "Syntax", 1, 1),
        ("<a>", "Syntax", 1, 4),
        ("<a>\n<b>\r\n\r\r</c>", "Syntax", 5, 1),
        ("<a/><b/>", "Syntax", 1, 5),
        ("<a b='1' b='2'/>", "Syntax", 1, 10),
        ("<1a/>", "Syntax", 1, 2),
        ("<a>]]></a>", "Syntax", 1, 4),
        ("<a>&#xD800;</a>", "Syntax", 1, 4),
        ("<a>&unknown;</a>", "Syntax", 1, 4),
        ("<a><!-- a -- b --></a>", "Syntax", 1, 11),
    ]
    for document, kind, line, column in cases:
        for chunks in splits(document):
            assert (yield from failure(decode_string(chunks))) == (kind, line, column), chunks
    for chunks in splits("<a><b/>text</c>"):
        results = yield from (
            stream.from_iterable(chunks, chunk_size=1)
            .pipe_through_channel(xml.decode_string())
            .result()
            .run_collect()
        )
        assert [
            type(result.value).__name__ if isinstance(result, Ok) else result.error.kind
            for result in results
            if isinstance(result, Ok | Err)
        ] == ["StartElement", "StartElement", "EndElement", "Syntax"]


@testing.effect
def test_limits_token_size_and_nesting_depth() -> Any:
    """limits token size and nesting depth"""
    limits = [
        ("<a>", "0123456789", "</a>"),
        ("<a>", "<![CDATA[0123456789]]>", "</a>"),
        ("", "<a b='0123456789'/>", ""),
        ("", "<!--0123456789-->", "<a/>"),
        ("", "<?pi 0123456789?>", "<a/>"),
        ("", "<!DOCTYPE a [<!ENTITY e 'x'>]>", "<a/>"),
    ]
    for before, token, after in limits:
        for chunks in splits(before + token + after):
            assert len((yield from decode_string(chunks, max_token_size=len(token)))) > 0
            assert (yield from failure(decode_string(chunks, max_token_size=len(token) - 1))) == (
                "Limit",
                1,
                len(before) + 1,
            )
    nested = "<a><a><a/></a></a>"
    assert len((yield from decode_string([nested], max_depth=3))) == 6
    assert (yield from failure(decode_string([nested], max_depth=2))) == ("Limit", 1, 7)


@testing.effect
def test_bounds_aggregate_open_names_and_releases_them_on_close() -> Any:
    """bounds aggregate open names and releases them on close"""
    document = "<aaaa><bbbb><cccc></cccc><dddd></dddd></bbbb><eeee></eeee></aaaa>"
    for chunks in splits(document):
        assert len((yield from decode_string(chunks, max_token_size=12))) == 10
    oversized = "<aaaa><bbbb><cccc><dddd></dddd></cccc></bbbb></aaaa>"
    for chunks in splits(oversized):
        assert (yield from decode_string(chunks, max_token_size=12).flip()).kind == "Limit"


def test_rejects_invalid_options_at_construction() -> None:
    """rejects invalid options at construction"""
    for value in (0, math.nan):
        with pytest.raises(ValueError):
            xml.decode_string(max_token_size=value)
        with pytest.raises(ValueError):
            xml.decode(max_depth=value)
        with pytest.raises(ValueError):
            xml.elements(["a"], max_element_size=value)
    with pytest.raises(ValueError):
        xml.elements([])
    with pytest.raises(ValueError):
        xml.elements(["a b"])


@testing.effect
def test_delivers_a_complete_start_tag_before_pulling_the_next_event() -> Any:
    """delivers a complete start tag before pulling the next event"""
    pulls: list[Event] = []

    def note(event: Event) -> fx.Effect[None]:
        return fx.sync(lambda: pulls.append(event))

    output = yield from (
        stream.from_iterable(
            [start("stream", {"xmlns": "jabber:client"}), end("stream")], chunk_size=1
        )
        .tap(note)
        .pipe_through_channel(xml.encode_string())
        .take(1)
        .run_collect()
    )
    assert output == ['<stream xmlns="jabber:client">']
    assert len(pulls) == 1


@testing.effect
def test_writes_events_as_escaped_xml() -> Any:
    """writes events as escaped XML"""
    empty: list[Event] = [start("a"), start("b"), end("b"), end("a")]
    assert (yield from encode_string(empty)) == "<a><b></b></a>"
    assert (
        yield from stream.from_iterable(empty, chunk_size=1)
        .pipe_through_channel(xml.encode_string())
        .run_collect()
    ) == ["<a>", "<b>", "</b>", "</a>"]
    escaped: list[Event] = [
        start("a", {"b": "<&>\"'\t\n\r"}),
        text("<&> ]]> \"' \t\n\r"),
        end("a"),
    ]
    written = '<a b="&lt;&amp;>&quot;\'&#9;&#10;&#13;">&lt;&amp;&gt; ]]&gt; "\' \t\n&#13;</a>'
    assert (yield from encode_string(escaped)) == written
    assert (yield from decode_string([written])) == escaped
    document = (
        '<?xml version="1.0"?><!DOCTYPE feed SYSTEM "feed.dtd"><!--c-->'
        '<feed xmlns:a="urn:a" a:b=\'&lt;"\'><a:entry>x &amp; <![CDATA[<y>]]>\r\n</a:entry>'
        "<e/><?p d?></feed>"
    )
    decoded = yield from decode_string([document])
    encoded = yield from (
        stream.from_iterable(decoded).pipe_through_channel(xml.encode()).run_collect()
    )
    assert (yield from decode_bytes(encoded)) == decoded


@testing.effect
def test_fails_on_events_that_do_not_form_a_document() -> Any:
    """fails on events that do not form a document"""
    declaration = Declaration("1.0")
    doctype = Doctype("a")
    cases: list[list[Event]] = [
        [],
        [start("a")],
        [start("a"), end("b")],
        [end("a")],
        [start("a"), end("a"), start("b"), end("b")],
        [start("a"), end("a"), text("x")],
        [start("1a"), end("1a")],
        [start("a", {"b c": ""}), end("a")],
        [start("a"), text("\0"), end("a")],
        [start("a", {"b": "￿"}), end("a")],
        [start("a"), comment("a--b"), end("a")],
        [start("a"), comment("a-"), end("a")],
        [start("a"), pi("xml", "x"), end("a")],
        [start("a"), pi("p", "?>"), end("a")],
        [start("a"), pi("p q", ""), end("a")],
        [comment(""), declaration, start("a"), end("a")],
        [Declaration("2.0"), start("a"), end("a")],
        [Declaration("1.0", 'UTF-8"'), start("a"), end("a")],
        [start("a"), end("a"), doctype],
        [doctype, doctype, start("a"), end("a")],
        [Doctype("a ["), start("a"), end("a")],
        [Doctype("a", "p"), start("a"), end("a")],
        [Doctype("a", '"', "s"), start("a"), end("a")],
        [Doctype("a", None, "'\""), start("a"), end("a")],
    ]
    for events in cases:
        error = yield from encode_string(events).flip()
        assert error.kind == "InvalidEvent", events
        assert (error.line, error.column) == (None, None)
    for encoding in ("ISO-8859-1", "US-ASCII"):
        declared: list[Event] = [Declaration("1.0", encoding), start("a"), end("a")]
        events = stream.from_iterable(declared)
        assert (yield from events.pipe_through_channel(xml.encode_string()).run_string()) == (
            f'<?xml version="1.0" encoding="{encoding}"?><a></a>'
        )
        error = yield from events.pipe_through_channel(xml.encode()).run_drain().flip()
        assert error.kind == "InvalidEvent", encoding
    invalid: list[Event] = [start("a"), text("x"), end("b")]
    results = yield from (
        stream.from_iterable(invalid)
        .pipe_through_channel(xml.encode_string())
        .result()
        .run_collect()
    )
    assert [
        result.value if isinstance(result, Ok) else result.error.kind
        for result in results
        if isinstance(result, Ok | Err)
    ] == ["<a>x", "InvalidEvent"]


@testing.effect
def test_collects_the_elements_at_a_path() -> Any:
    """collects the elements at a path"""
    document = "<a><item id='1'><item id='2'>x</item></item><b><item/></b> <item id='3'/></a>"
    assert (yield from elements(document, ["a", "item"])) == [
        Element("item", {"id": "1"}, (Element("item", {"id": "2"}, ("x",)),)),
        Element("item", {"id": "3"}, ()),
    ]
    found = yield from elements(document, ["a", "*", "item"])
    assert [element.attributes for element in found] == [{"id": "2"}, {}]


@testing.effect
def test_fails_on_oversized_elements_and_unbalanced_events() -> Any:
    """fails on oversized elements and unbalanced events"""
    document = "<a>" + "<b c='12'><d>3</d></b>" * 2 + "</a>"
    assert len((yield from elements(document, ["a", "b"], max_element_size=6))) == 2
    error = yield from elements(document, ["a", "b"], max_element_size=5).flip()
    assert error.kind == "Limit"
    cases: list[list[Event]] = [[end("a")], [start("a")]]
    for events in cases:
        error = yield from (
            stream.from_iterable(events)
            .pipe_through_channel(xml.elements(["a"]))
            .run_drain()
            .flip()
        )
        assert error.kind == "InvalidEvent"
        assert (error.line, error.column) == (None, None)


@testing.effect
def test_propagate_upstream_errors_and_done_values() -> Any:
    """propagate upstream errors and done values"""
    error = yield from (
        stream.make("<a><b>")
        .concat(stream.fail("upstream"))
        .pipe_through_channel(xml.decode_string())
        .run_drain()
        .flip()
    )
    assert error == "upstream"

    def events() -> Any:
        yield from [start("a"), end("a")]
        return "done"

    source: Any = channel.from_iterator_array(events)
    assert (yield from source.pipe_to(xml.encode()).run_drain()) == "done"


@testing.effect
def test_emit_elements_before_pulling_the_rest_of_the_input() -> Any:
    """emit elements before pulling the rest of the input"""
    pulls: list[str] = []

    def note(chunk: str) -> fx.Effect[None]:
        return fx.sync(lambda: pulls.append(chunk))

    item = yield from (
        stream.from_iterable(["<a>", "<item/>", "<item/>", "</a>"], chunk_size=1)
        .tap(note)
        .pipe_through_channel(xml.decode_string())
        .pipe_through_channel(xml.elements(["a", "item"]))
        .take(1)
        .run_collect()
    )
    assert item == [Element("item", {}, ())]
    assert len(pulls) == 2
