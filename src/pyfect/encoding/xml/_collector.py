"""``elements``: events to the trees at a path."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pyfect._js import js_length
from pyfect.encoding.xml._model import (
    Element,
    EndElement,
    Event,
    StartElement,
    Text,
    XmlError,
    invalid_event,
)


class _Open:
    __slots__ = ("attributes", "children", "name")

    def __init__(self, name: str, attributes: Mapping[str, str]) -> None:
        self.name = name
        self.attributes = attributes
        self.children: list[Element | str] = []


class Collector:
    def __init__(self, path: Sequence[str], max_element_size: float) -> None:
        self.out: list[Element] = []
        self._path = path
        self._max_element_size = max_element_size
        self._depth = 0
        # Number of open elements, from the root, that match the path
        self._matched = 0
        # The element being collected and its open descendants
        self._stack: list[_Open] = []
        self._size = 0

    def push(self, value: Event, /) -> None:
        if isinstance(value, StartElement):
            self._start(value)
        elif isinstance(value, EndElement):
            self._end(value)
        elif isinstance(value, Text):
            self._text(value)

    def _start(self, event: StartElement) -> None:
        depth = self._depth
        self._depth += 1
        if not self._stack:
            if self._matched != depth:
                return
            segment = self._path[depth]
            if segment not in ("*", event.name):
                return
            self._matched += 1
            if self._matched < len(self._path):
                return
            self._size = 0
        self._stack.append(_Open(event.name, event.attributes))
        size = js_length(event.name)
        for key, value in event.attributes.items():
            size += js_length(key) + js_length(value)
        self._grow(size)

    def _end(self, event: EndElement) -> None:
        if self._depth == 0:
            raise invalid_event(f"end tag </{event.name}> without a start tag")
        if self._stack:
            opened = self._stack.pop()
            element = Element(opened.name, opened.attributes, tuple(opened.children))
            if self._stack:
                self._stack[-1].children.append(element)
            else:
                self.out.append(element)
        if self._matched == self._depth:
            self._matched -= 1
        self._depth -= 1

    def _text(self, event: Text) -> None:
        if not self._stack or not event.text:
            return
        self._grow(js_length(event.text))
        children = self._stack[-1].children
        if children and isinstance(children[-1], str):
            children[-1] += event.text
        else:
            children.append(event.text)

    def end(self) -> None:
        if self._depth > 0:
            raise invalid_event("events ended inside an element")

    def _grow(self, size: int) -> None:
        self._size += size
        if self._size > self._max_element_size:
            raise XmlError(
                "Limit",
                f"element <{self._stack[0].name}> exceeds maxElementSize of "
                f"{_limit(self._max_element_size)}",
            )


def _limit(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)
