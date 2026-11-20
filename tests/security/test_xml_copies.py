"""The XML parser and writer copy each character a bounded number of times however many tokens,
sections or events it comes in. Counted with ``_copies``: timing sees these copies only at sizes
a test can't afford."""

from typing import Any

from _copies import Copies
from _guards import guards

import pyfect as fx
from pyfect import stream
from pyfect.encoding import xml

N = 2000


def _run(elements: list[Any], channel: Any, chunk_size: int = 1) -> None:
    program = stream.from_iterable(elements, chunk_size=chunk_size).pipe_through_channel(channel)
    exit = fx.run_blocking_exit(program.run_collect())
    assert isinstance(exit, fx.Success), exit


@guards("6e8ffaef", "xml-long-token-window-copied")
def test_tags_past_max_token_size_are_not_copied_for_each_tag() -> None:
    """#41: each tag was parsed from a copy of the chunk up to its window."""
    copies = Copies()
    document = "<r>" + "<a/>" * N + "</r>"
    _run([copies.text(document)], xml.decode_string(max_token_size=64))
    assert copies.characters <= len(document)


@guards("6e8ffaef", "xml-cdata-text-concatenated")
def test_text_split_by_cdata_sections_is_not_copied_for_each_section() -> None:
    """#43: the text so far was copied in front of each CDATA section."""
    copies = Copies()
    document = "<r>" + "xxxxxxxxxxxx<![CDATA[]]>" * N + "</r>"
    _run([copies.text(document)], xml.decode_string())
    assert copies.characters <= len(document)


@guards("6e8ffaef", "xml-output-concatenated")
def test_output_is_not_copied_for_each_event() -> None:
    """#44: the output so far was copied in front of each event's text. Whitespace after the
    root is written as given, so the counting strings reach the writer's output."""
    for encode in (xml.encode_string(), xml.encode()):
        copies = Copies()
        events = [
            xml.StartElement("r", {}),
            xml.EndElement("r"),
            *(xml.Text(copies.text("\n")) for _ in range(N)),
        ]
        _run(events, encode, chunk_size=len(events))
        assert copies.characters <= N
