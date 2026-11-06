"""Reading the records of an XML document one at a time."""

import pyfect as fx
from pyfect import stream
from pyfect.encoding import xml

document = """<feed>
  <item id="1"><title>First</title></item>
  <item id="2"><title>Second &amp; last</title></item>
</feed>"""


def describe(item: xml.Element) -> str:
    title = next(child for child in item.children if isinstance(child, xml.Element))
    return f"{item.attributes['id']}: {title.children[0]}"


# The document can arrive in chunks split anywhere.
chunks = stream.make(document[:30], document[30:])
items = (
    chunks.pipe_through_channel(xml.decode_string())
    .pipe_through_channel(xml.elements(["feed", "item"]))
    .map(describe)
)
print(fx.run_blocking(items.run_collect().or_die()))

events: list[xml.Event] = [
    xml.StartElement("note", {"to": "Ada & Grace"}),
    xml.Text("1 < 2"),
    xml.EndElement("note"),
]
written = stream.from_iterable(events).pipe_through_channel(xml.encode_string())
print(fx.run_blocking(written.run_string().or_die()))
