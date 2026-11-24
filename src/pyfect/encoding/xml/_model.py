"""The events, trees and error of ``pyfect.encoding.xml``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from pyfect.errors import TaggedError

type XmlErrorKind = Literal["Syntax", "Unsupported", "Limit", "InvalidEvent"]


@dataclass(eq=False)
class XmlError(TaggedError):
    """XML could not be decoded or encoded.

    - ``"Syntax"``: the input is not well-formed XML or not valid UTF-8, or, with
      ``namespaces="strict"``, not namespace-well-formed.
    - ``"Unsupported"``: the input uses a feature this module does not process,
      such as an entity declared in a DOCTYPE or a byte encoding other than UTF-8.
    - ``"Limit"``: the input exceeds ``max_token_size``, ``max_depth`` or
      ``max_element_size``.
    - ``"InvalidEvent"``: the events do not form a well-formed document.

    Errors from ``decode`` and ``decode_string`` carry the one-based ``line`` and
    ``column`` of the problem, also at the end of ``message``. Columns count
    UTF-16 code units, and lines end at LF, CR or CRLF."""

    kind: XmlErrorKind
    message: str
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class Declaration:
    """The XML declaration at the start of a document."""

    version: str
    encoding: str | None = None
    standalone: bool | None = None


@dataclass(frozen=True, slots=True)
class Doctype:
    """A document type declaration. ``public_id`` and ``system_id`` name an
    external DTD, which is never read; the internal subset is not reported."""

    name: str
    public_id: str | None = None
    system_id: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class StartElement:
    """A start tag, with its attributes in document order. ``name`` is the
    qualified name as written. ``<br/>`` is a ``StartElement`` then an
    ``EndElement``.

    With ``positions=True``, ``line`` and ``column`` locate the tag's ``<`` as an
    ``XmlError`` would. With ``namespaces="strict"``, ``namespace`` (``""`` for
    none) and ``local_name`` are the resolved name; attributes stay keyed as
    written, and ``xmlns`` declarations stay attributes. Otherwise these fields
    are ``None``. The encoders ignore them."""

    name: str
    attributes: Mapping[str, str] = field(default_factory=dict[str, str], hash=False)
    line: int | None = None
    column: int | None = None
    namespace: str | None = None
    local_name: str | None = None

    def __repr__(self) -> str:
        position = "" if self.line is None else f", line={self.line}, column={self.column}"
        resolved = (
            ""
            if self.local_name is None
            else f", namespace={self.namespace!r}, local_name={self.local_name!r}"
        )
        return (
            f"StartElement(name={self.name!r}, attributes={self.attributes!r}{position}{resolved})"
        )


@dataclass(frozen=True, slots=True)
class EndElement:
    """An end tag. With ``namespaces="strict"``, ``namespace`` and
    ``local_name`` repeat those of the start tag; otherwise they are ``None``."""

    name: str
    namespace: str | None = None
    local_name: str | None = None


@dataclass(frozen=True, slots=True)
class Text:
    """Character data inside the root element. Adjacent text, references and
    CDATA sections are one ``Text`` however the input is chunked, with line
    endings normalized to ``\\n``."""

    text: str


@dataclass(frozen=True, slots=True)
class Comment:
    """A comment: the text between ``<!--`` and ``-->``."""

    text: str


@dataclass(frozen=True, slots=True)
class ProcessingInstruction:
    """A processing instruction. ``data`` is the text after the target, without
    leading whitespace."""

    target: str
    data: str


type Event = (
    Declaration | Doctype | StartElement | EndElement | Text | Comment | ProcessingInstruction
)
"""What the decoders write and the encoders read."""


@dataclass(frozen=True, slots=True)
class Element:
    """An element ``elements`` collected. Children are elements and strings of
    character data in document order: adjacent text is one string, and comments
    and processing instructions are dropped."""

    name: str
    attributes: Mapping[str, str] = field(default_factory=dict[str, str], hash=False)
    children: tuple[Element | str, ...] = ()


def invalid_event(message: str) -> XmlError:
    return XmlError("InvalidEvent", message)
