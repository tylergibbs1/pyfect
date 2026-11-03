"""Which nodes become definitions (``$defs``): Effect's reference
allocation in ``toRepresentation``.

JSON Schema describes the encoded side, so each position is the node at the
end of its encoding chain (a schema class: its fields' struct). A node with
an ``identifier`` is a definition under that name (by default; a
``ReferencePolicy`` decides otherwise); a node reached with no identifier of
its own from one that has one (a class's struct, a number's JSON form) is
named after it, ``<identifier>Encoded``. A recursive node is always a
definition. Repeated names get ``_1``, ``_2``... suffixes.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from pyfect.schema import ast
from pyfect.schema._jsonschema._annotations import ReferenceCandidate, ReferencePolicy
from pyfect.schema._jsonschema._checks import schemas_of


def _class_next(node: ast.AST) -> ast.AST | None:
    if isinstance(node, ast.Class):
        if node.side == "decode":
            return node.shape.fields
        if node.side == "encoded":
            return node.shape.encoded
    return None


def _next(node: ast.AST) -> ast.AST | None:
    if node.encoding is not None:
        return node.encoding[-1].to
    return _class_next(node)


def encoded_node(node: ast.AST) -> ast.AST:
    """The node at the end of ``node``'s encoding chain."""
    while (next_node := _next(node)) is not None:
        node = next_node
    return node


@dataclass(frozen=True, slots=True)
class Content:
    """The document a string holds (JSON text): its media type and the
    candidate of the values it encodes."""

    media_type: str
    schema: Candidate | None


FALLBACK_KEY = "~identifier"
"""The annotation naming the node a definition was reached from, kept on
the definition (``to_representation``) so its name survives a round trip."""


def _identifier(node: ast.AST, key: str = "identifier") -> str | None:
    identifier = (node.resolve() or {}).get(key)
    return identifier if isinstance(identifier, str) else None


@dataclass(eq=False)
class Candidate:
    """A node that may become a definition."""

    ast: ast.AST
    identifier: str | None
    fallback: str | None
    """The identifier of the node it was reached from, when it has none."""
    content: Content | None = None
    occurrences: int = 0
    visiting: bool = False
    recursive: bool = False
    reference: str | None = None


def children(node: ast.AST) -> Iterator[ast.AST]:
    """The nodes inside ``node`` (an encoded node)."""
    match node:
        case ast.Declaration():
            yield from node.type_parameters
        case ast.Objects():
            for p in node.properties:
                yield p.type
            for i in node.index_signatures:
                yield i.parameter
                yield i.type
        case ast.Arrays():
            for e in node.elements:
                yield e.type
            yield from node.rest
        case ast.Union():
            yield from node.types
        case ast.Suspend():
            yield node.target
        case ast.TemplateLiteral():
            yield from node.parts
        case _:
            pass


def default_policy(candidate: ReferenceCandidate) -> str | None:
    return candidate.identifier


class References:
    """The candidates of some root nodes, with their references decided."""

    def __init__(self, roots: Sequence[ast.AST], policy: ReferencePolicy | None) -> None:
        self._candidates: dict[int, list[Candidate]] = {}
        self._used: set[str] = set()
        self._types: dict[int, tuple[ast.AST, ast.AST]] = {}
        for root in roots:
            self._visit(root)
        decide = policy or default_policy
        for variants in self._candidates.values():
            for candidate in variants:
                self._decide(candidate, decide)

    def _decide(self, candidate: Candidate, policy: ReferencePolicy) -> None:
        requested = policy(
            ReferenceCandidate(candidate.ast, candidate.occurrences, candidate.identifier)
        )
        if requested is not None:
            separator = (
                "_" if requested == candidate.identifier or not requested.endswith("_") else ""
            )
            candidate.reference = self._reference(requested, separator)
        elif candidate.recursive:
            candidate.reference = self._reference(f"{candidate.ast.tag}_", "")

    def _reference(self, prefix: str, separator: str) -> str:
        reference = prefix
        suffix = 0
        while reference in self._used:
            suffix += 1
            reference = f"{prefix}{separator}{suffix}"
        self._used.add(reference)
        return reference

    def candidate(self, input: ast.AST, links: int | None = None) -> Candidate:
        """The candidate of ``input`` through its first ``links`` encoding
        links (all of them by default)."""
        node = input
        length = len(node.encoding or ()) if links is None else links
        content: Content | None = None
        while True:
            if node.encoding is not None and length > 0:
                last = node.encoding[length - 1]
                found = getattr(last.transformation, "content", None)
                # Only the link writing the final string says what it holds.
                if found is not None and last.to.encoding is None and last.to.tag == "String":
                    held = self.candidate(node, length - 1) if found.preserve_schema else None
                    content = Content(found.media_type, held)
                node = last.to
                length = len(node.encoding or ())
                continue
            following = _class_next(node)
            if following is None:
                break
            node = following
            length = len(node.encoding or ())
        if node.encoding is not None and node.body_owner is not None:
            # Stopped before an encoding: the schema it was added to.
            node = node.body_owner
        node = node.owner()
        identifier = _identifier(node)
        fallback = None
        if identifier is None:
            fallback = _identifier(input) if node is not input else None
            if fallback is None:
                fallback = _identifier(node, FALLBACK_KEY)
            if fallback is not None:
                identifier = f"{fallback}Encoded"
        variants = self._candidates.setdefault(id(node), [])
        for candidate in variants:
            if candidate.identifier == identifier and candidate.content == content:
                return candidate
        candidate = Candidate(node, identifier, fallback, content)
        variants.append(candidate)
        return candidate

    def _visit(self, input: ast.AST) -> None:
        self._visit_candidate(self.candidate(input))

    def _visit_candidate(self, candidate: Candidate) -> None:
        candidate.occurrences += 1
        if candidate.visiting:
            candidate.recursive = True
            return
        if candidate.occurrences > 1:
            return
        candidate.visiting = True
        if candidate.content is not None and candidate.content.schema is not None:
            self._visit_candidate(candidate.content.schema)
        self._visit_checks(candidate.ast.checks)
        for child in children(candidate.ast):
            self._visit(child)
        candidate.visiting = False

    def check_schemas(self, check: ast.Check[object]) -> list[ast.AST]:
        """The decoded sides of the schemas a check names, the same nodes
        each time (a candidate is a node)."""
        out: list[ast.AST] = []
        for schema in schemas_of(check.annotations):
            if isinstance(schema, ast.AST):
                hit = self._types.get(id(schema))
                if hit is None:
                    hit = (schema, schema.to_type())
                    self._types[id(schema)] = hit
                out.append(hit[1])
        return out

    def _visit_checks(self, checks: ast.Checks | None) -> None:
        for check in checks or ():
            for schema in self.check_schemas(check):
                self._visit(schema)
            if isinstance(check, ast.FilterGroup):
                self._visit_checks(check.checks)
