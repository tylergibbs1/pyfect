"""Namespaces in XML 1.0 for the decoder's ``namespaces="strict"``: the
bindings of open elements, and the resolved name of each element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pyfect._js import js_length
from pyfect.encoding.xml._chars import is_name_start

XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
XMLNS_NAMESPACE = "http://www.w3.org/2000/xmlns/"


class NamespaceError(Exception):
    """A violation the parser reports at the start tag's ``<``."""

    def __init__(self, kind: Literal["Syntax", "Unsupported", "Limit"], message: str) -> None:
        super().__init__(message)
        self.kind: Literal["Syntax", "Unsupported", "Limit"] = kind
        self.message = message


@dataclass(frozen=True, slots=True)
class Resolved:
    namespace: str
    local_name: str
    # The length of the undo log before the element's declarations
    undo: int


def _qname_colon(kind: str, name: str) -> int:
    """The index of the colon in a qualified name, or -1 when it has none."""
    colon = name.find(":")
    if colon != -1 and (
        colon == 0
        or colon == len(name) - 1
        or name.find(":", colon + 1) != -1
        or not is_name_start(name[colon + 1])
    ):
        raise NamespaceError("Syntax", f"{kind} name {name} is not a qualified name")
    return colon


def check_target(target: str) -> None:
    if ":" in target:
        raise NamespaceError("Syntax", f"processing instruction target {target} contains a colon")


class Scopes:
    """The bindings in scope. A prefix that is not bound has no entry, and the
    default namespace is the prefix ``""``."""

    def __init__(self, max_token_size: float, limit: str) -> None:
        self._max_token_size = max_token_size
        self._limit = limit
        self._bindings: dict[str, str] = {"xml": XML_NAMESPACE}
        # The prefix and previous binding of each change that open elements made,
        # which end tags undo
        self._undo: list[tuple[str, str | None]] = []
        self._open: list[Resolved] = []
        # The size of the declarations of open elements, in UTF-16 code units
        self._declaration_size = 0

    def open(
        self, name: str, attributes: Mapping[str, str], self_closing: bool, doctype: bool
    ) -> Resolved:
        """Applies the declarations of a start tag and resolves its names."""
        undo = len(self._undo)
        prefixed = 0
        for attribute, uri in attributes.items():
            colon = _qname_colon("attribute", attribute)
            if attribute == "xmlns":
                prefix = ""
            elif attribute.startswith("xmlns:"):
                prefix = attribute[6:]
            else:
                if colon != -1:
                    prefixed += 1
                continue
            self._declare(attribute, prefix, uri)
        if not self_closing and self._declaration_size > self._max_token_size:
            raise NamespaceError(
                "Limit",
                f"namespace declarations of open elements exceed maxTokenSize of {self._limit}",
            )
        namespace = self._bindings.get("", "")
        local_name = name
        colon = _qname_colon("element", name)
        if colon != -1:
            prefix = name[:colon]
            if prefix == "xmlns":
                raise NamespaceError("Syntax", f"element name {name} cannot use the xmlns prefix")
            found = self._bindings.get(prefix)
            if found is None:
                raise _undeclared(
                    f"namespace prefix {prefix} of element {name} is not declared", doctype
                )
            namespace = found
            local_name = name[colon + 1 :]
        if prefixed > 0:
            self._check_prefixed(attributes, prefixed > 1, doctype)
        resolved = Resolved(namespace, local_name, undo)
        self._open.append(resolved)
        return resolved

    def _declare(self, attribute: str, prefix: str, uri: str) -> None:
        if prefix == "xml":
            if uri != XML_NAMESPACE:
                raise NamespaceError("Syntax", f"xmlns:xml can only bind {XML_NAMESPACE}")
            return
        if prefix == "xmlns":
            raise NamespaceError("Syntax", "xmlns:xmlns cannot be declared")
        if uri in (XML_NAMESPACE, XMLNS_NAMESPACE):
            raise NamespaceError("Syntax", f"{attribute} cannot bind the reserved namespace {uri}")
        if uri == "" and prefix != "":
            raise NamespaceError("Syntax", f"{attribute} cannot be empty")
        current = self._bindings.get(prefix)
        if (current or "") == uri:
            return
        self._undo.append((prefix, current))
        self._bind(prefix, uri or None)
        self._declaration_size += js_length(prefix) + js_length(uri)

    def _check_prefixed(self, attributes: Mapping[str, str], several: bool, doctype: bool) -> None:
        """Prefixed attributes are resolved once every declaration of the tag
        is applied. Unprefixed attributes have no namespace, so a duplicate
        takes two prefixed ones."""
        seen: dict[str, set[str]] = {}
        for attribute in attributes:
            colon = attribute.find(":")
            if colon == -1 or attribute.startswith("xmlns:"):
                continue
            prefix = attribute[:colon]
            namespace = self._bindings.get(prefix)
            if namespace is None:
                raise _undeclared(
                    f"namespace prefix {prefix} of attribute {attribute} is not declared", doctype
                )
            if not several:
                return
            local = attribute[colon + 1 :]
            locals_ = seen.setdefault(namespace, set())
            if local in locals_:
                raise NamespaceError(
                    "Syntax",
                    f"attribute {attribute} has the namespace and local name of another attribute",
                )
            locals_.add(local)

    def close(self) -> Resolved:
        """Ends the innermost open element's scope and returns its names."""
        resolved = self._open.pop()
        while len(self._undo) > resolved.undo:
            prefix, previous = self._undo.pop()
            # The binding in scope is the one this element made, which ends with it
            self._declaration_size -= js_length(prefix) + js_length(self._bindings.get(prefix, ""))
            self._bind(prefix, previous)
        return resolved

    def _bind(self, prefix: str, uri: str | None) -> None:
        if uri is None:
            self._bindings.pop(prefix, None)
        else:
            self._bindings[prefix] = uri


def _undeclared(message: str, doctype: bool) -> NamespaceError:
    # A DTD can declare a prefix with a default attribute value, which is not
    # applied, so an undeclared prefix is a Syntax error only without a DOCTYPE
    if doctype:
        return NamespaceError(
            "Unsupported", f"{message} (namespaces declared in a DTD are not applied)"
        )
    return NamespaceError("Syntax", message)
