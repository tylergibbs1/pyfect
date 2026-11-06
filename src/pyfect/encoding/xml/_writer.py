"""``encode`` and ``encode_string``: events to XML text."""

from __future__ import annotations

import re
from collections.abc import Mapping

from pyfect.encoding.xml._chars import (
    PUBID,
    code_point_at,
    is_name,
    is_reserved_target,
    is_whitespace,
    quoted,
    search_invalid,
)
from pyfect.encoding.xml._model import (
    Comment,
    Declaration,
    Doctype,
    EndElement,
    Event,
    ProcessingInstruction,
    StartElement,
    Text,
    invalid_event,
)
from pyfect.encoding.xml._parser import CONTENT, EPILOG

_NOTHING_WRITTEN = 3
_PROLOG = 0
_MAX_CACHED_NAMES = 1024

_TEXT_SPECIAL = re.compile(r"[&<>\r]")
_ATTRIBUTE_SPECIAL = re.compile(r'[&<"\t\n\r]')
_ESCAPES = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "\t": "&#9;",
    "\n": "&#10;",
    "\r": "&#13;",
}
_VERSION = re.compile(r"1\.[0-9]+")
_ENCODING = re.compile(r"[A-Za-z][A-Za-z0-9._-]*")


def _escape(match: re.Match[str]) -> str:
    return _ESCAPES[match[0]]


def _escape_text(text: str) -> str:
    return _TEXT_SPECIAL.sub(_escape, text)


def _escape_attribute(value: str) -> str:
    return _ATTRIBUTE_SPECIAL.sub(_escape, value)


def _check_chars(what: str, text: str) -> None:
    invalid = search_invalid(text)
    if invalid != -1:
        raise invalid_event(
            f"{what} contains the invalid character U+{code_point_at(text, invalid)}"
        )


def _check_name(what: str, name: object) -> None:
    if not isinstance(name, str) or not is_name(name):
        raise invalid_event(f"invalid {what} {quoted(name)}")


class Writer:
    def __init__(self, is_bytes: bool) -> None:
        self.out: list[str] = []
        self._stack: list[str] = []
        self._state = _NOTHING_WRITTEN
        self._doctype = False
        self._is_bytes = is_bytes
        # Element and attribute names already checked, which repeat in most
        # documents. Cleared when full, so that it stays small.
        self._names: set[str] = set()

    def _is_name(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        if name in self._names:
            return True
        if not is_name(name):
            return False
        if len(self._names) >= _MAX_CACHED_NAMES:
            self._names.clear()
        self._names.add(name)
        return True

    def _check_attributes(self, attributes: Mapping[str, str]) -> None:
        """Checks attributes one by one, in order, after a batched check has failed."""
        for name, value in attributes.items():
            if not self._is_name(name):
                _check_name("attribute name", name)
            if not isinstance(value, str):  # pyright: ignore[reportUnnecessaryIsInstance]
                raise invalid_event(f"attribute {name} must be a string")
            _check_chars(f"attribute {name}", value)

    def push(self, value: Event, /) -> None:
        text = self._write(value)
        if text:
            if self.out:
                self.out[0] += text
            else:
                self.out.append(text)

    def end(self) -> None:
        if self._stack:
            raise invalid_event(f"unclosed element <{self._stack[-1]}>")
        if self._state != EPILOG:
            raise invalid_event("no root element")

    def _write(self, event: Event) -> str:
        if isinstance(event, EndElement):
            return self._end_element(event)
        if isinstance(event, StartElement):
            return self._start_element(event)
        if isinstance(event, Text):
            return self._text(event)
        if isinstance(event, Comment):
            return self._comment(event)
        if isinstance(event, ProcessingInstruction):
            return self._processing_instruction(event)
        return self._declaration(event) if isinstance(event, Declaration) else self._doctype_(event)

    def _end_element(self, event: EndElement) -> str:
        open_name = self._stack[-1] if self._stack else None
        if open_name is None or event.name != open_name:
            # Only valid names are written into messages
            _check_name("element name", event.name)
            raise invalid_event(
                f"end tag </{event.name}> without a start tag"
                if open_name is None
                else f"end tag </{event.name}> does not match <{open_name}>"
            )
        self._stack.pop()
        if not self._stack:
            self._state = EPILOG
        return f"</{open_name}>"

    def _start_element(self, event: StartElement) -> str:
        if not self._is_name(event.name):
            _check_name("element name", event.name)
        if self._state == EPILOG:
            raise invalid_event(f"second root element <{event.name}>")
        parts = ["<", event.name]
        valid = True
        for name, value in event.attributes.items():
            if not isinstance(value, str) or not self._is_name(name):  # pyright: ignore[reportUnnecessaryIsInstance]
                valid = False
                break
            parts.append(f' {name}="{_escape_attribute(value)}"')
        tag = "".join(parts)
        # Escaping keeps invalid characters, so one search of the tag checks
        # every value; the first error is then found in attribute order
        if not valid or (len(tag) > len(event.name) + 1 and search_invalid(tag) != -1):
            self._check_attributes(event.attributes)
        self._stack.append(event.name)
        self._state = CONTENT
        return tag + ">"

    def _text(self, event: Text) -> str:
        _check_chars("text", event.text)
        if self._state == CONTENT:
            return _escape_text(event.text)
        if not is_whitespace(event.text):
            raise invalid_event("text outside the root element must be whitespace")
        if self._state == _NOTHING_WRITTEN and event.text:
            self._state = _PROLOG
        return event.text

    def _comment(self, event: Comment) -> str:
        _check_chars("comment", event.text)
        if "--" in event.text or event.text.endswith("-"):
            raise invalid_event('comments cannot contain "--" or end with "-"')
        if self._state == _NOTHING_WRITTEN:
            self._state = _PROLOG
        return f"<!--{event.text}-->"

    def _processing_instruction(self, event: ProcessingInstruction) -> str:
        _check_name("processing instruction target", event.target)
        if is_reserved_target(event.target):
            raise invalid_event(f"processing instruction target {event.target} is reserved")
        _check_chars("processing instruction", event.data)
        if "?>" in event.data:
            raise invalid_event('processing instruction data cannot contain "?>"')
        if self._state == _NOTHING_WRITTEN:
            self._state = _PROLOG
        return f"<?{event.target}{'' if event.data == '' else ' ' + event.data}?>"

    def _declaration(self, event: Declaration) -> str:
        if self._state != _NOTHING_WRITTEN:
            raise invalid_event("the XML declaration must be the first event")
        if _VERSION.fullmatch(event.version) is None:
            raise invalid_event(f"invalid XML version {quoted(event.version)}")
        declaration = f'<?xml version="{event.version}"'
        if event.encoding is not None:
            if _ENCODING.fullmatch(event.encoding) is None:
                raise invalid_event(f"invalid encoding name {quoted(event.encoding)}")
            if self._is_bytes and event.encoding.lower() != "utf-8":
                raise invalid_event(
                    f"encoding {event.encoding} cannot be declared for UTF-8 output"
                )
            declaration += f' encoding="{event.encoding}"'
        if event.standalone is not None:
            declaration += f' standalone="{"yes" if event.standalone else "no"}"'
        self._state = _PROLOG
        return declaration + "?>"

    def _doctype_(self, event: Doctype) -> str:
        if self._state in (CONTENT, EPILOG) or self._doctype:
            raise invalid_event("a DOCTYPE must appear once, before the root element")
        _check_name("DOCTYPE name", event.name)
        doctype = f"<!DOCTYPE {event.name}"
        if event.public_id is not None:
            if event.system_id is None:
                raise invalid_event("a DOCTYPE with a public identifier needs a system identifier")
            if PUBID.fullmatch(event.public_id) is None:
                raise invalid_event(f"invalid public identifier {quoted(event.public_id)}")
            doctype += f' PUBLIC "{event.public_id}"'
        if event.system_id is not None:
            _check_chars("system identifier", event.system_id)
            has_double = '"' in event.system_id
            if has_double and "'" in event.system_id:
                raise invalid_event("a system identifier cannot contain both quote characters")
            if event.public_id is None:
                doctype += " SYSTEM"
            doctype += f" '{event.system_id}'" if has_double else f' "{event.system_id}"'
        self._doctype = True
        self._state = _PROLOG
        return doctype + ">"
